from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from shared import config, store, timeline

QUERY = """
alertsmanagementresources
| where type == "microsoft.alertsmanagement/alerts"
| where todatetime(properties.essentials.startDateTime) > ago(30d)
| project id = extract("([^/]+)$", 1, id),
          alertRule = tostring(properties.essentials.alertRule),
          severity = tostring(properties.essentials.severity),
          monitorCondition = tostring(properties.essentials.monitorCondition),
          alertState = tostring(properties.essentials.alertState),
          signalType = tostring(properties.essentials.signalType),
          targetResource = tolower(tostring(properties.essentials.targetResource)),
          targetResourceName = tostring(properties.essentials.targetResourceName),
          targetResourceGroup = tolower(tostring(properties.essentials.targetResourceGroup)),
          startTime = tostring(properties.essentials.startDateTime),
          resolvedTime = tostring(properties.essentials.monitorConditionResolvedDateTime),
          description = tostring(properties.essentials.description)
"""

SEVERITY_MAP = {"sev0": "critical", "sev1": "critical", "sev2": "warning", "sev3": "info", "sev4": "info"}


def _query_alerts() -> list[dict]:
    client = ResourceGraphClient(store.credential())
    options = QueryRequestOptions(result_format="objectArray", top=1000)
    request = QueryRequest(subscriptions=[config.subscription_id()], query=QUERY, options=options)
    return list(client.resources(request).data)


def _alert_doc(a: dict) -> dict:
    start = timeline.parse_iso(a["startTime"])
    resolved = a.get("resolvedTime") or ""
    return {
        "id": a["id"],
        "day": start.strftime("%Y-%m-%d"),
        "type": "alert",
        "alertRule": a["alertRule"],
        "severity": a["severity"],
        "monitorCondition": a["monitorCondition"],
        "alertState": a["alertState"],
        "signalType": a["signalType"],
        "resourceId": a["targetResource"],
        "resourceName": a["targetResourceName"],
        "resourceGroup": a["targetResourceGroup"],
        "startTime": timeline.iso(start),
        "resolvedTime": timeline.iso(timeline.parse_iso(resolved)) if resolved else "",
        "description": a.get("description") or "",
    }


def _alert_events(doc: dict) -> list[dict]:
    target = doc["resourceName"] or "subscription"
    common = dict(
        source="azure-monitor",
        resource_id=doc["resourceId"],
        resource_name=doc["resourceName"],
        resource_group=doc["resourceGroup"],
    )
    details = {"alertRule": doc["alertRule"], "severity": doc["severity"], "signalType": doc["signalType"]}
    events = [timeline.make_event(
        event_type="alert",
        severity=SEVERITY_MAP.get(doc["severity"].lower(), "warning"),
        title=f"Alert fired: {doc['alertRule']} on {target}",
        timestamp=timeline.parse_iso(doc["startTime"]),
        details=details,
        **common,
    )]
    if doc["monitorCondition"] == "Resolved" and doc["resolvedTime"]:
        events.append(timeline.make_event(
            event_type="alert",
            severity="info",
            title=f"Alert resolved: {doc['alertRule']} on {target}",
            timestamp=timeline.parse_iso(doc["resolvedTime"]),
            details=details,
            **common,
        ))
    return events


def collect() -> dict:
    now = timeline.utc_now()
    docs = [_alert_doc(a) for a in _query_alerts()]
    events = [e for d in docs for e in _alert_events(d)]

    for doc in docs:
        store.upsert("alerts", doc)
    for event in events:
        store.upsert("events", event)
    blob_path = f"alerts/{now:%Y-%m-%d}/{now:%H%M%S}.json"
    store.archive_json(blob_path, {"timestamp": timeline.iso(now), "alerts": docs})

    return {
        "alerts": len(docs),
        "fired": sum(1 for d in docs if d["monitorCondition"] == "Fired"),
        "resolved": sum(1 for d in docs if d["monitorCondition"] == "Resolved"),
        "events": len(events),
        "blob": f"raw-snapshots/{blob_path}",
    }