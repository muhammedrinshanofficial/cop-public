import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

from shared import config, store, timeline

API_URL = (
    "https://management.azure.com/subscriptions/{sub}"
    "/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
)

DAYS_BACK = 30          # how much history each run pulls
BASELINE_DAYS = 7       # a day is compared with the average of the days before it
MIN_HISTORY_DAYS = 3    # no spike check without at least this many earlier days
SPIKE_RATIO = 2.0       # spike = at least 2x the usual cost ...
MIN_INCREASE = 20.0     # ... and at least this much more (billing currency, INR here)
MAX_RETRIES = 4
MAX_WAIT_SECONDS = 60

RETRY_HEADERS = (
    "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-clienttype-retry-after",
    "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after",
    "Retry-After",
)
RG_PATTERN = re.compile(r"/resourcegroups/([^/]+)", re.IGNORECASE)


def _retry_wait(resp, attempt: int) -> int:
    for header in RETRY_HEADERS:
        value = resp.headers.get(header)
        if value and value.isdigit():
            return min(int(value), MAX_WAIT_SECONDS)
    return min(10 * attempt, MAX_WAIT_SECONDS)


def _post(url: str, body: dict, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.post(url, json=body, headers=headers, timeout=60)
        if resp.status_code != 429 or attempt == MAX_RETRIES:
            break
        time.sleep(_retry_wait(resp, attempt))
    if resp.status_code != 200:
        raise RuntimeError(f"Cost Management returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _query_costs(now: datetime) -> tuple[list[dict], datetime]:
    start = (now - timedelta(days=DAYS_BACK)).replace(hour=0, minute=0, second=0, microsecond=0)
    body = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {"from": timeline.iso(start), "to": timeline.iso(now)},
        "dataset": {
            "granularity": "Daily",
            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            "grouping": [{"type": "Dimension", "name": "ResourceId"}],
        },
    }
    token = store.credential().get_token("https://management.azure.com/.default").token
    url = API_URL.format(sub=config.subscription_id())
    rows: list[dict] = []
    while url:
        data = _post(url, body, token)
        props = data.get("properties", {})
        names = [c["name"] for c in props.get("columns", [])]
        for r in props.get("rows", []):
            rows.append(dict(zip(names, r)))
        url = props.get("nextLink")
    return rows, start


def _aggregate(rows: list[dict]) -> tuple[dict, dict, dict, str]:
    resources: dict[str, dict] = {}
    by_day: dict[str, float] = defaultdict(float)
    by_group: dict[str, float] = defaultdict(float)
    currency = ""
    for r in rows:
        cost = float(r.get("Cost") or 0)
        raw_day = str(r.get("UsageDate"))
        day = f"{raw_day[0:4]}-{raw_day[4:6]}-{raw_day[6:8]}"
        rid = (r.get("ResourceId") or "").lower() or "unassigned"
        match = RG_PATTERN.search(rid)
        group = match.group(1) if match else ""
        currency = currency or r.get("Currency") or ""

        entry = resources.setdefault(rid, {
            "resourceId": rid,
            "name": rid.rsplit("/", 1)[-1],
            "resourceGroup": group,
            "total": 0.0,
            "daily": defaultdict(float),
        })
        entry["total"] += cost
        entry["daily"][day] += cost
        by_day[day] += cost
        by_group[group or "unassigned"] += cost
    return resources, by_day, by_group, currency


def _spike(series: dict, target: str):
    history = sorted(d for d in series if d < target)[-BASELINE_DAYS:]
    if len(history) < MIN_HISTORY_DAYS:
        return None
    baseline = sum(series[d] for d in history) / len(history)
    value = series.get(target, 0.0)
    if baseline > 0 and value >= baseline * SPIKE_RATIO and value - baseline >= MIN_INCREASE:
        return value, baseline
    return None


def _detect_spikes(resources: dict, by_day: dict, currency: str, today: str) -> list[dict]:
    # Today is only partly billed, so the newest finished day is the one we judge.
    finished = sorted(d for d in by_day if d < today)
    if not finished:
        return []
    target = finished[-1]
    ts = datetime.strptime(target, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    events = []

    total = _spike(by_day, target)
    if total:
        value, baseline = total
        events.append(timeline.make_event(
            event_type="cost", severity="warning", source="cost-management",
            title=f"Daily cost spike on {target}: {value:.2f} {currency} (usual {baseline:.2f})",
            timestamp=ts, resource_name="subscription",
            details={"day": target, "cost": round(value, 2), "baseline": round(baseline, 2), "currency": currency},
        ))

    for rid, r in resources.items():
        found = _spike(r["daily"], target)
        if found:
            value, baseline = found
            events.append(timeline.make_event(
                event_type="cost", severity="warning", source="cost-management",
                title=f"Cost spike: {r['name']} {value:.2f} {currency} on {target} (usual {baseline:.2f})",
                timestamp=ts, resource_id=rid, resource_name=r["name"], resource_group=r["resourceGroup"],
                details={"day": target, "cost": round(value, 2), "baseline": round(baseline, 2), "currency": currency},
            ))
    return events


def collect() -> dict:
    now = timeline.utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    rows, start = _query_costs(now)
    resources, by_day, by_group, currency = _aggregate(rows)
    events = _detect_spikes(resources, by_day, currency, now.strftime("%Y-%m-%d"))

    resource_list = sorted(resources.values(), key=lambda r: r["total"], reverse=True)
    snapshot = {
        "id": f"cost-{stamp}",
        "type": "cost",
        "timestamp": timeline.iso(now),
        "day": now.strftime("%Y-%m-%d"),
        "currency": currency,
        "periodFrom": timeline.iso(start),
        "periodTo": timeline.iso(now),
        "totalCost": round(sum(by_day.values()), 2),
        "byDay": {d: round(v, 4) for d, v in sorted(by_day.items())},
        "byResourceGroup": {g: round(v, 4) for g, v in by_group.items()},
        "byResource": [
            {
                "resourceId": r["resourceId"],
                "name": r["name"],
                "resourceGroup": r["resourceGroup"],
                "total": round(r["total"], 4),
                "daily": {d: round(v, 4) for d, v in sorted(r["daily"].items())},
            }
            for r in resource_list
        ],
    }

    store.upsert("snapshots", snapshot)
    for event in events:
        store.upsert("events", event)
    blob_path = f"cost/{now:%Y-%m-%d}/{now:%H%M%S}.json"
    store.archive_json(blob_path, snapshot)
    store.upsert("snapshots", {**snapshot, "id": "cost-latest"})

    return {
        "snapshotId": snapshot["id"],
        "rows": len(rows),
        "resources": len(resource_list),
        "totalCost": snapshot["totalCost"],
        "currency": currency,
        "events": len(events),
        "blob": f"raw-snapshots/{blob_path}",
    }