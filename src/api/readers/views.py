from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from shared import store, timeline

MAX_EVENTS = 500
TOP_RESOURCES = 15
DETAIL_RESOURCES = 5   # only the biggest few resources carry their daily series


def _clean(doc: dict | None) -> dict | None:
    """Drop the Cosmos system fields (_rid, _etag, _ts ...) so the browser only sees our own data."""
    if doc is None:
        return None
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def _latest(doc_id: str, partition: str) -> dict | None:
    return _clean(store.read_item("snapshots", doc_id, partition))


def _missing(what: str, collector: str) -> dict:
    return {"available": False, "message": f"No {what} data yet. Run /api/collect/{collector} first."}


def _days(count: int) -> list[str]:
    today = timeline.utc_now().date()
    return [(today - timedelta(days=i)).isoformat() for i in range(count)]


def _per_day(container: str, sql: str, days: list[str]) -> list[dict]:
    """One query per day partition, run in parallel, so every query stays inside a single partition."""
    def one(day: str) -> list[dict]:
        return store.query(container, sql, [{"name": "@d", "value": day}], partition_key=day)

    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(one, days))
    return [_clean(item) for batch in batches for item in batch]


def _count_by(items: list[dict], key: str) -> dict:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


TYPE_NAMES = {
    "microsoft.compute/virtualmachines": "Virtual machine",
    "microsoft.compute/disks": "Disk",
    "microsoft.network/networkinterfaces": "Network interface",
    "microsoft.network/publicipaddresses": "Public IP",
    "microsoft.network/networksecuritygroups": "Network security group",
    "microsoft.network/virtualnetworks": "Virtual network",
    "microsoft.storage/storageaccounts": "Storage account",
    "microsoft.web/serverfarms": "App Service plan",
    "microsoft.web/sites": "App Service / Function App",
    "microsoft.web/staticsites": "Static Web App",
    "microsoft.documentdb/databaseaccounts": "Cosmos DB",
    "microsoft.cognitiveservices/accounts": "Azure OpenAI / AI service",
    "microsoft.operationalinsights/workspaces": "Log Analytics workspace",
    "microsoft.insights/components": "Application Insights",
    "microsoft.insights/metricalerts": "Metric alert rule",
    "microsoft.insights/activitylogalerts": "Activity Log alert rule",
    "microsoft.keyvault/vaults": "Key Vault",
    "microsoft.monitor/observabilityagents": "Observability Agent",
}


def resource_type(resource_id: str) -> str:
    """A readable type from a resource ID, for example 'Virtual machine'. Unknown types show the raw type word."""
    tail = (resource_id or "").lower().split("/providers/")
    if len(tail) < 2:
        return ""
    seg = tail[-1].split("/")            # namespace / type / name / child type / child name
    types = seg[1::2]
    if not types:
        return ""
    return TYPE_NAMES.get(seg[0] + "/" + "/".join(types)) or types[-1]


# ---------------------------------------------------------------- alerts and timeline

def alerts(days: int = 30) -> dict:
    items = _per_day("alerts", "SELECT * FROM c WHERE c.day = @d", _days(days))
    items.sort(key=lambda a: a.get("startTime", ""), reverse=True)
    return {
        "days": days,
        "count": len(items),
        "fired": sum(1 for a in items if a.get("monitorCondition") == "Fired"),
        "resolved": sum(1 for a in items if a.get("monitorCondition") == "Resolved"),
        "bySeverity": _count_by(items, "severity"),
        "alerts": items,
    }


def timeline_events(days: int = 7, event_type: str = "", severity: str = "",
                    resource: str = "", search: str = "", limit: int = 200) -> dict:
    limit = max(1, min(limit, MAX_EVENTS))
    window = _per_day("events", "SELECT * FROM c WHERE c.day = @d ORDER BY c.timestamp DESC", _days(days))

    # The counts for the filter buttons ignore the type and severity filters, so they stay stable while filtering.
    facets = {"types": _count_by(window, "eventType"), "severities": _count_by(window, "severity")}

    def keep(e: dict) -> bool:
        if event_type and e.get("eventType", "").lower() != event_type.lower():
            return False
        if severity and e.get("severity", "").lower() != severity.lower():
            return False
        if resource and resource.lower() not in f"{e.get('resourceName', '')} {e.get('resourceId', '')}".lower():
            return False
        if search and search.lower() not in f"{e.get('title', '')} {e.get('resourceName', '')}".lower():
            return False
        return True

    matched = [e for e in window if keep(e)]
    matched.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return {
        "days": days,
        "total": len(matched),
        "returned": min(len(matched), limit),
        "truncated": len(matched) > limit,
        "facets": facets,
        "events": matched[:limit],
    }


# ---------------------------------------------------------------- snapshot based views

def inventory() -> dict:
    snap = _latest("inventory-latest", "inventory")
    if not snap:
        return _missing("inventory", "inventory")
    resources = snap.get("resources", [])
    return {
        "available": True,
        "timestamp": snap.get("timestamp"),
        "count": snap.get("count", len(resources)),
        "byType": snap.get("byType", {}),
        "byResourceGroup": _count_by(resources, "resourceGroup"),
        "byLocation": _count_by(resources, "location"),
        "resources": resources,
    }


def cost(only: list | None = None) -> dict:
    snap = _latest("cost-latest", "cost")
    if not snap:
        return _missing("cost", "cost")
    forecast = _latest("cost-forecast-latest", "cost-forecast")

    by_resource = snap.get("byResource", [])
    all_groups = sorted(snap.get("byResourceGroup", {}))
    by_day, by_group, grand = snap.get("byDay", {}), snap.get("byResourceGroup", {}), snap.get("totalCost", 0)
    if only:
        by_resource = [r for r in by_resource if r["resourceGroup"] in only]
        by_day, by_group = {}, {}
        for r in by_resource:
            k = r["resourceGroup"] or "unassigned"
            by_group[k] = by_group.get(k, 0) + r["total"]
            for d, c in (r.get("daily") or {}).items():
                by_day[d] = by_day.get(d, 0) + c
        grand = round(sum(by_group.values()), 2)
    top = []
    for i, r in enumerate(by_resource[:TOP_RESOURCES]):
        item = {"resourceId": r["resourceId"], "name": r["name"], "type": resource_type(r["resourceId"]),
                "resourceGroup": r["resourceGroup"], "total": r["total"]}
        if i < DETAIL_RESOURCES:
            item["daily"] = [{"day": d, "cost": c} for d, c in sorted(r.get("daily", {}).items())]
        top.append(item)

    groups = sorted(by_group.items(), key=lambda kv: kv[1], reverse=True)

    # Cost of each day split by resource: the top 10 resources and the rest as one number.
    per_day: dict = {}
    for r in by_resource:
        for day, c in (r.get("daily") or {}).items():
            if c >= 0.005:
                per_day.setdefault(day, []).append(
                    {"name": r["name"], "type": resource_type(r["resourceId"]),
                     "resourceGroup": r["resourceGroup"], "cost": round(c, 2)})
    day_detail = {}
    for day, items in per_day.items():
        items.sort(key=lambda i: i["cost"], reverse=True)
        total = round(sum(i["cost"] for i in items), 2)
        day_detail[day] = {"total": total, "items": items[:10],
                           "others": round(sum(i["cost"] for i in items[10:]), 2)}
    return {
        "available": True,
        "timestamp": snap.get("timestamp"),
        "currency": snap.get("currency", ""),
        "periodFrom": snap.get("periodFrom"),
        "periodTo": snap.get("periodTo"),
        "totalCost": grand,
        "daily": [{"day": d, "cost": c} for d, c in sorted(by_day.items())],
        "byResourceGroup": [{"name": n or "unassigned", "cost": c} for n, c in groups],
        "topResources": top,
        "resourceCount": len(by_resource),
        "perDay": day_detail,
        "forecast": forecast,
        "allGroups": all_groups,
        "filtered": bool(only),
    }


def metrics() -> dict:
    snap = _latest("metrics-latest", "metrics")
    if not snap:
        return _missing("metrics", "metrics")
    return {"available": True, **snap}


def utilization() -> dict:
    util = _latest("vm-utilization-latest", "vm-utilization")
    waste = _latest("waste-latest", "waste")
    if not util and not waste:
        return _missing("right-sizing and waste", "utilization")
    return {"available": True, "utilization": util, "waste": waste}


def quota() -> dict:
    snap = _latest("quota-latest", "quota")
    if not snap:
        return _missing("quota", "quota")
    return {"available": True, **snap}


def security() -> dict:
    snap = _latest("security-latest", "security")
    if not snap:
        return _missing("security", "security")
    return {"available": True, **snap}


def overview() -> dict:
    inv = _latest("inventory-latest", "inventory")
    cst = _latest("cost-latest", "cost")
    fc = _latest("cost-forecast-latest", "cost-forecast")
    util = _latest("vm-utilization-latest", "vm-utilization")
    waste = _latest("waste-latest", "waste")
    sec = _latest("security-latest", "security")
    alert_data = alerts(30)
    recent = timeline_events(days=3, limit=8)

    vms = (util or {}).get("vms", [])
    daily = sorted((cst or {}).get("byDay", {}).items())[-14:]
    budget = (fc or {}).get("budget") or {}
    return {
        "generatedAt": timeline.iso(timeline.utc_now()),
        "currency": (cst or fc or {}).get("currency", ""),
        "inventory": None if not inv else {"count": inv.get("count", 0), "byType": inv.get("byType", {})},
        "cost": None if not cst else {
            "totalCost30d": cst.get("totalCost", 0),
            "daily": [{"day": d, "cost": c} for d, c in daily],
            "byResourceGroup": cst.get("byResourceGroup", {}),
        },
        "forecast": None if not fc else {
            "status": fc.get("status"), "percentOfBudget": fc.get("percentOfBudget"),
            "forecastMonthEnd": fc.get("forecastMonthEnd"), "budget": budget.get("amount"),
            "spentThroughYesterday": fc.get("spentThroughYesterday"), "confidence": fc.get("confidence"),
        },
        "vms": None if not util else {
            "total": len(vms),
            "overProvisioned": sum(1 for v in vms if v.get("status") == "over-provisioned"),
            "highUtilization": sum(1 for v in vms if v.get("status") == "high-utilization"),
            "rightSized": sum(1 for v in vms if v.get("status") == "right-sized"),
            "insufficientData": sum(1 for v in vms if v.get("status") == "insufficient-data"),
            "potentialMonthlySaving": util.get("potentialMonthlySaving", 0),
        },
        "waste": None if not waste else {"count": waste.get("count", 0), "byType": waste.get("byType", {})},
        "security": None if not sec else {
            "count": sec.get("count", 0), "bySeverity": sec.get("bySeverity", {}), "byType": sec.get("byType", {}),
        },
        "alerts": {"fired": sum(1 for a in alert_data["alerts"]
                                if a.get("monitorCondition") == "Fired" and a.get("signalType") not in ("Log", "Activity Log")),
                   "resolved": alert_data["resolved"],
                   "total": alert_data["count"], "latest": alert_data["alerts"][:3]},
        "recentEvents": recent["events"],
        "freshness": {
            "inventory": (inv or {}).get("timestamp"), "cost": (cst or {}).get("timestamp"),
            "forecast": (fc or {}).get("timestamp"), "utilization": (util or {}).get("timestamp"),
            "waste": (waste or {}).get("timestamp"), "security": (sec or {}).get("timestamp"),
        },
    }