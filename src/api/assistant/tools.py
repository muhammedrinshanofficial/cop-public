import json
import re
from datetime import timedelta

from readers import views
from shared import timeline

PROJECT_TAG = "azure-cloud-operations-center"
COP_WORD = re.compile(r"(^|[\s\-_/])cop([\s\-_]|$)", re.IGNORECASE)
PATH = re.compile(r"/subscriptions/\S+/", re.IGNORECASE)
MAX_RESULT_CHARS = 12000   # a tool result is never larger than this, so one answer stays cheap


def _tidy(text) -> str:
    return PATH.sub("", str(text or ""))


def _mine(o: dict) -> bool:
    """Same rule as the dashboard: tagged for this project, or the name or group contains the word cop."""
    if (o.get("tags") or {}).get("project") == PROJECT_TAG:
        return True
    fields = [o.get("resourceGroup"), o.get("name"), o.get("resourceName"), o.get("alertRule"), o.get("title")]
    return bool(COP_WORD.search(" ".join(str(f) for f in fields if f)))


def _scoped(items: list, scope: str) -> list:
    return items if scope == "all" else [i for i in items if _mine(i)]


def _num(value, default: int, low: int, high: int) -> int:
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return default


def _scope(args: dict) -> str:
    return "all" if args.get("scope") == "all" else "project"


def _count(items: list, key: str) -> dict:
    out: dict = {}
    for i in items:
        k = str(i.get(key) or "unknown")
        out[k] = out.get(k, 0) + 1
    return out


def _sev(s: str) -> str:
    return {"Sev0": "critical", "Sev1": "critical", "Sev2": "warning"}.get(s, "info")


def _event(e: dict) -> dict:
    out = {"time": e.get("timestamp"), "type": e.get("eventType"), "severity": e.get("severity"),
           "title": _tidy(e.get("title")), "resource": e.get("resourceName"), "resourceGroup": e.get("resourceGroup")}
    error = (e.get("details") or {}).get("error")
    if error:
        out["error"] = str(error)[:300]
    return out


# ---------------------------------------------------------------- the eight tools (all read-only, fixed parameters)

def get_inventory(args: dict) -> dict:
    d = views.inventory()
    if d.get("available") is False:
        return d
    scope, group, rtype = _scope(args), str(args.get("resource_group") or "").lower(), str(args.get("resource_type") or "").lower()
    items = [r for r in _scoped(d["resources"], scope)
             if (not group or r["resourceGroup"] == group) and (not rtype or rtype in r["type"])]
    return {"scope": scope, "count": len(items), "byResourceGroup": _count(items, "resourceGroup"),
            "byType": dict(sorted(_count(items, "type").items(), key=lambda kv: -kv[1])[:15]),
            "resources": [{"name": r["name"], "type": r["type"].split("/")[-1], "resourceGroup": r["resourceGroup"],
                           "location": r.get("location"), "sku": r.get("skuName") or None} for r in items[:40]],
            "truncated": len(items) > 40, "snapshotTime": d.get("timestamp")}


def _cost_day(value, d: dict) -> str:
    """'yesterday', 'latest' or a date like 2026-10-19."""
    v = str(value or "").strip().lower()
    if v == "yesterday":
        return (timeline.utc_now().date() - timedelta(days=1)).isoformat()
    days = sorted(d.get("perDay") or {})
    if v == "latest":
        return days[-1] if days else ""
    m = re.match(r"^\d{4}-(\d{2}-\d{2})$", v)
    if m and v not in days:   # the model may guess the wrong year: match the month and day instead
        for day in reversed(days):
            if day.endswith("-" + m.group(1)):
                return day
    return v


def _cost_one_day(d: dict, day: str, scope: str) -> dict:
    x = (d.get("perDay") or {}).get(day)
    if not x:
        return {"scope": scope, "day": day, "available": False, "message": "No cost data for that day.",
                "daysWithData": sorted(d.get("perDay") or {})[-14:]}
    items = [i for i in x["items"] if scope == "all" or _mine(i)]
    return {"scope": scope, "currency": d["currency"], "day": day, "subscriptionTotalThatDay": x["total"],
            "listedResourcesTotal": round(sum(i["cost"] for i in items), 2), "resources": items, "smallerResourcesSubscriptionWide": x["others"],
            "note": "subscriptionTotalThatDay covers every project in the subscription, so do not present it as this project's cost when scope is project. Only the ten biggest resources of the whole subscription are listed for a day. Cost data lags up to a day, so the newest day can still grow."}


def get_cost_summary(args: dict) -> dict:
    d = views.cost()
    if d.get("available") is False:
        return d
    scope = _scope(args)
    if args.get("day"):
        return _cost_one_day(d, _cost_day(args.get("day"), d), scope)
    groups = [g for g in d["byResourceGroup"] if scope == "all" or _mine({"resourceGroup": g["name"]})]
    top = [r for r in d["topResources"] if scope == "all" or _mine(r)][:10]
    f = d.get("forecast") or {}
    return {"scope": scope, "currency": d["currency"], "period": [d.get("periodFrom"), d.get("periodTo")],
            "subscriptionTotal30d": d["totalCost"], "scopeTotal30d": round(sum(g["cost"] for g in groups), 2),
            "byResourceGroup": groups, "topResources": [{"name": r["name"], "type": r.get("type"), "resourceGroup": r["resourceGroup"], "cost": r["total"]} for r in top],
            "dailyLast7": d["daily"][-7:],
            "forecastSubscription": {"monthEnd": f.get("forecastMonthEnd"), "low": f.get("forecastLow"), "high": f.get("forecastHigh"),
                                     "budget": (f.get("budget") or {}).get("amount"), "percentOfBudget": f.get("percentOfBudget"),
                                     "status": f.get("status"), "confidence": f.get("confidence")},
            "note": "Cost data lags up to a day. Forecast, budget and the subscription total cover the whole subscription."}


def get_resource_metrics(args: dict) -> dict:
    d = views.metrics()
    if d.get("available") is False:
        return d
    needle = str(args.get("vm_name") or "").lower()
    vms = []
    for v in d["vms"]:
        if needle and needle not in v["name"].lower():
            continue
        m = v.get("memory") or {}
        vms.append({"name": v["name"], "cpuPercent": v.get("cpuPct"),
                    "memoryUsedMB": {"avg": m.get("avgUsedMB"), "p95": m.get("p95UsedMB"), "max": m.get("maxUsedMB"), "samples": m.get("samples")} if m else None})
    return {"windowDays": d.get("windowDays"), "vms": vms, "note": "A VM with null values had no samples (it was probably switched off)."}


def get_recent_changes(args: dict) -> dict:
    hours, scope = _num(args.get("hours"), 24, 1, 168), _scope(args)
    d = views.timeline_events(days=hours // 24 + 2, resource=str(args.get("resource") or ""), limit=500)
    cutoff = timeline.iso(timeline.utc_now() - timedelta(hours=hours))
    items = [e for e in _scoped(d["events"], scope) if e.get("eventType") in ("change", "deployment", "health") and e.get("timestamp", "") >= cutoff]
    return {"scope": scope, "hours": hours, "total": len(items), "byType": _count(items, "eventType"), "events": [_event(e) for e in items[:40]], "truncated": len(items) > 40}


def get_alerts(args: dict) -> dict:
    days, scope, state = _num(args.get("days"), 7, 1, 30), _scope(args), str(args.get("state") or "").lower()
    d = views.alerts(days)
    items = _scoped(d["alerts"], scope)
    if state in ("fired", "resolved"):
        items = [a for a in items if a.get("monitorCondition", "").lower() == state]
    return {"scope": scope, "days": days, "total": len(items), "fired": sum(1 for a in items if a.get("monitorCondition") == "Fired"),
            "resolved": sum(1 for a in items if a.get("monitorCondition") == "Resolved"),
            "alerts": [{"rule": _tidy(a.get("alertRule")), "resource": a.get("resourceName"), "severity": _sev(a.get("severity")), "state": a.get("monitorCondition"),
                        "signal": a.get("signalType"), "started": a.get("startTime"), "resolved": a.get("resolvedTime") or None} for a in items[:30]],
            "note": "Activity Log alerts, for example failed deployments, have no resolve event and stay Fired."}


def get_deployments(args: dict) -> dict:
    days, scope, only_failed = _num(args.get("days"), 7, 1, 30), _scope(args), bool(args.get("only_failed"))
    d = views.timeline_events(days=days, event_type="deployment", limit=500)
    items = _scoped(d["events"], scope)
    failed = [e for e in items if e.get("severity") == "error"]
    shown = failed if only_failed else items
    return {"scope": scope, "days": days, "total": len(items), "failed": len(failed), "deployments": [_event(e) for e in shown[:30]], "truncated": len(shown) > 30}


def get_security_findings(args: dict) -> dict:
    d = views.security()
    if d.get("available") is False:
        return d
    scope = _scope(args)
    items = _scoped(d["findings"], scope)
    return {"scope": scope, "count": len(items), "bySeverity": _count(items, "severity"), "byType": _count(items, "type"), "lastScan": d.get("timestamp"),
            "findings": [{"severity": f["severity"], "type": f["type"], "resource": f["name"], "resourceGroup": f["resourceGroup"], "reason": f["reason"]} for f in items[:30]],
            "note": "Firewall and public IP scans cover the whole subscription. The tag check covers only this project."}


def get_vm_utilization_vs_cost(args: dict) -> dict:
    d = views.utilization()
    if d.get("available") is False:
        return d
    scope = _scope(args)
    u, w = d.get("utilization") or {}, d.get("waste") or {}
    vms = _scoped(u.get("vms") or [], scope)
    out = []
    for v in vms:
        rec = v.get("recommendation") or {}
        out.append({"name": v["name"], "size": v["vmSize"], "vcpus": v.get("vcpus"), "memoryMB": v.get("memoryMB"), "status": v["status"], "powerState": (v.get("powerState") or "").replace("PowerState/", "") or None,
                    "cpuP95Percent": (v.get("cpuPct") or {}).get("p95"), "memoryP95Percent": (v.get("memoryUsedPct") or {}).get("p95"),
                    "listPricePerMonth": v.get("monthlyListPrice"), "billedLast30Days": v.get("billedCost30d"), "reasons": v.get("reasons"),
                    "recommendedSize": rec.get("size"), "estimatedMonthlySaving": rec.get("estimatedMonthlySaving")})
    saving = sum(x["estimatedMonthlySaving"] or 0 for x in out if x["status"] == "over-provisioned")
    waste = _scoped(w.get("findings") or [], scope)
    return {"scope": scope, "snapshotTime": u.get("timestamp"), "currency": u.get("currency") or w.get("currency"), "potentialMonthlySaving": round(saving, 2), "vms": out,
            "waste": [{"kind": f["type"], "resource": f["name"], "reason": f["reason"], "billedLast30Days": f["billedCost30d"]} for f in waste[:20]],
            "note": "Savings are list-price estimates. The VMs shut down every night, so real savings are smaller."}


_SCOPE = {"type": "string", "enum": ["project", "all"], "description": "project = only this project's resources (default); all = the whole shared subscription"}


def _spec(name: str, description: str, properties: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "additionalProperties": False}}}


TOOL_SPECS = [
    _spec("get_inventory", "List the Azure resources: counts by type and resource group, and the resource names.",
          {"scope": _SCOPE, "resource_group": {"type": "string", "description": "optional resource group name"}, "resource_type": {"type": "string", "description": "optional text in the type, for example virtualmachines"}}),
    _spec("get_cost_summary", "Cost of the last 30 days, per resource group and per resource, plus the month-end forecast and budget. Pass day to get the cost of each resource on that one day, for example to explain a cost spike.",
          {"scope": _SCOPE, "day": {"type": "string", "description": "optional: a date like 2026-10-19, or yesterday, or latest"}}),
    _spec("get_resource_metrics", "CPU and memory statistics of the virtual machines over the last 7 days.", {"vm_name": {"type": "string", "description": "optional part of a VM name"}}),
    _spec("get_recent_changes", "Resource changes, deployments and VM health events (went unavailable, available again, and the cause) in the last N hours. Use this for what changed yesterday or today, or whether a VM was down.",
          {"hours": {"type": "integer", "description": "1 to 168, default 24"}, "resource": {"type": "string", "description": "optional part of a resource name"}, "scope": _SCOPE}),
    _spec("get_alerts", "Fired and resolved alerts from Azure Monitor.", {"days": {"type": "integer", "description": "1 to 30, default 7"}, "state": {"type": "string", "enum": ["fired", "resolved"]}, "scope": _SCOPE}),
    _spec("get_deployments", "Deployments from the Activity Log, with the error text of failed ones.", {"days": {"type": "integer", "description": "1 to 30, default 7"}, "only_failed": {"type": "boolean"}, "scope": _SCOPE}),
    _spec("get_security_findings", "Security findings: internet-open firewall rules, public IPs and missing tags.", {"scope": _SCOPE}),
    _spec("get_vm_utilization_vs_cost", "Right-sizing: VM size, price, billed cost and real CPU and memory use, the recommended smaller size, and waste (idle, stopped or unattached resources).", {"scope": _SCOPE}),
]
HANDLERS = {"get_inventory": get_inventory, "get_cost_summary": get_cost_summary, "get_resource_metrics": get_resource_metrics, "get_recent_changes": get_recent_changes,
            "get_alerts": get_alerts, "get_deployments": get_deployments, "get_security_findings": get_security_findings, "get_vm_utilization_vs_cost": get_vm_utilization_vs_cost}


def run_tool(name: str, raw_arguments: str) -> str:
    """Run one tool by name. The model can only pick from HANDLERS; anything else is refused."""
    handler = HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Unknown tool {name}. Use only the tools you were given."})
    try:
        args = json.loads(raw_arguments or "{}")
        if not isinstance(args, dict):
            args = {}
    except ValueError:
        args = {}
    try:
        text = json.dumps(handler(args), default=str)
    except Exception as exc:
        return json.dumps({"error": f"The data could not be read ({type(exc).__name__})."})
    if len(text) > MAX_RESULT_CHARS:   # keep the result valid JSON and tell the model it was cut
        text = json.dumps({"truncated": True, "partialData": text[:MAX_RESULT_CHARS - 200]})
    return text