import json

import requests

from shared import config, store, timeline

LOG_ANALYTICS_URL = "https://api.loganalytics.io/v1/workspaces/{ws}/query"
DEPLOYMENT_OP = "microsoft.resources/deployments/write"

ACTIVITY_QUERY = """
AzureActivity
| where CategoryValue == "Administrative"
| where ActivityStatusValue in ("Succeeded", "Success", "Failed", "Failure")
| where OperationNameValue endswith "/WRITE" or OperationNameValue endswith "/DELETE"
| project TimeGenerated, OperationNameValue, Status = ActivityStatusValue,
          ResourceGroup, ResourceId = tolower(_ResourceId), Caller, CorrelationId,
          Properties = tostring(Properties)
| order by TimeGenerated asc
| take 1000
"""


def _query_rows(days: int, query: str = ACTIVITY_QUERY) -> list[dict]:
    token = store.credential().get_token("https://api.loganalytics.io/.default").token
    url = LOG_ANALYTICS_URL.format(ws=config.log_analytics_workspace_id())
    body = {"query": query, "timespan": f"P{days}D"}
    resp = requests.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Log Analytics returned {resp.status_code}: {resp.text[:300]}")
    rows = []
    for table in resp.json().get("tables", []):
        names = [c["name"] for c in table.get("columns", [])]
        for row in table.get("rows", []):
            rows.append(dict(zip(names, row)))
    return rows


def _error_text(props: str) -> str:
    """Pull the error code and message out of a failed operation's status message."""
    try:
        message = json.loads(props).get("statusMessage", "")
        if isinstance(message, str):
            try:
                message = json.loads(message)
            except ValueError:
                return message[:500]
        if not isinstance(message, dict):
            return ""
        error = message.get("error")
        if not isinstance(error, dict):
            error = message  # some operations put code and message at the top level
        return f"{error.get('code', '')}: {error.get('message', '')}".strip(": ")[:500]
    except Exception:
        return ""


def _borrowed_errors(rows: list[dict]) -> dict[str, str]:
    """A failed deployment row has no error text, but the failed operations inside it share its correlation ID."""
    found: dict[str, list[str]] = {}
    for r in rows:
        if r["Status"] in ("Failed", "Failure"):
            text = _error_text(r.get("Properties") or "")
            texts = found.setdefault(r.get("CorrelationId") or "", [])
            if text and text not in texts and len(texts) < 3:
                texts.append(text)
    return {corr: " | ".join(texts)[:500] for corr, texts in found.items() if texts}


def _to_event(r: dict, borrowed: dict[str, str]) -> dict:
    op = str(r["OperationNameValue"]).lower()
    resource_type, action = op.rsplit("/", 1)
    rid = (r.get("ResourceId") or "").lower()
    name = rid.rsplit("/", 1)[-1] if rid else ""
    failed = r["Status"] in ("Failed", "Failure")
    details = {
        "operation": op,
        "status": r["Status"],
        "caller": r.get("Caller") or "",
        "correlationId": r.get("CorrelationId") or "",
    }
    if failed:
        details["error"] = _error_text(r.get("Properties") or "") or borrowed.get(r.get("CorrelationId") or "", "")

    if op == DEPLOYMENT_OP:
        event_type = "deployment"
        severity = "error" if failed else "info"
        title = f"Deployment {'failed' if failed else 'succeeded'}: {name}"
    else:
        event_type = "change"
        if failed:
            severity, title = "error", f"Operation failed: {action} {name} ({resource_type})"
        elif action == "delete":
            severity, title = "warning", f"Resource deleted: {name} ({resource_type})"
        else:
            severity, title = "info", f"Resource changed: {name} ({resource_type})"

    return timeline.make_event(
        event_type=event_type,
        severity=severity,
        source="activity-log",
        title=title,
        timestamp=timeline.parse_iso(r["TimeGenerated"]),
        resource_id=rid,
        resource_name=name,
        resource_group=r.get("ResourceGroup") or "",
        details=details,
    )


HEALTH_QUERY = """
AzureActivity
| where CategoryValue == "ResourceHealth"
| where ActivityStatusValue in ("Active", "Resolved")
| project TimeGenerated, Status = ActivityStatusValue, ResourceId = tolower(_ResourceId), Properties = tostring(Properties)
| order by TimeGenerated asc
| take 1000
"""


def _health_event(r: dict) -> dict:
    """One health event per outage start (Active) and per recovery (Resolved). The Updated rows are noise and are not read."""
    try:
        p = json.loads(r.get("Properties") or "{}")
    except ValueError:
        p = {}
    if not isinstance(p, dict):
        p = {}
    rid = (r.get("ResourceId") or "").lower()
    name = str(p.get("resource") or "").lower() or (rid.rsplit("/", 1)[-1] if rid else "")
    cause = str(p.get("cause") or "")
    if r["Status"] == "Resolved":
        severity, title = "info", f"Health: {name} available again"
    else:
        user = cause == "UserInitiated"
        severity = "info" if user else "warning"
        title = f"Health: {name} unavailable ({'user initiated' if user else (cause or 'cause unknown').lower()})"
    return timeline.make_event(
        event_type="health", severity=severity, source="resource-health", title=title,
        timestamp=timeline.parse_iso(r["TimeGenerated"]), resource_id=rid, resource_name=name,
        resource_group=str(p.get("resourceGroup") or ""),
        details={"status": r["Status"], "cause": cause, "type": p.get("type"), "title": p.get("title"),
                 "details": p.get("details"), "previous": p.get("previousHealthStatus"), "current": p.get("currentHealthStatus")},
    )


def collect(days: int = 2) -> dict:
    now = timeline.utc_now()
    rows = _query_rows(days)
    borrowed = _borrowed_errors(rows)
    events = [_to_event(r, borrowed) for r in rows]
    health_rows = _query_rows(days, HEALTH_QUERY)
    events += [_health_event(r) for r in health_rows]

    for event in events:
        store.upsert("events", event)
    blob_path = f"activity/{now:%Y-%m-%d}/{now:%H%M%S}.json"
    store.archive_json(blob_path, {"timestamp": timeline.iso(now), "days": days, "rows": rows})

    return {
        "days": days,
        "rows": len(rows),
        "events": len(events),
        "deployments": sum(1 for e in events if e["eventType"] == "deployment"),
        "health": len(health_rows),
        "failed": sum(1 for e in events if e["severity"] == "error"),
        "blob": f"raw-snapshots/{blob_path}",
    }