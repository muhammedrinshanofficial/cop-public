import requests

from shared import config, store, timeline

ARM_URL = "https://management.azure.com"
REGION = "swedencentral"
WARN_PCT = 80.0   # at or above this share of a limit, a warning event is written (one per limit per day)


def _usages(token: str) -> list[dict]:
    url = f"{ARM_URL}/subscriptions/{config.subscription_id()}/providers/Microsoft.Compute/locations/{REGION}/usages"
    resp = requests.get(url, params={"api-version": "2024-07-01"}, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Azure returned {resp.status_code}: {resp.text[:300]}")
    return resp.json().get("value", [])


def collect() -> dict:
    now = timeline.utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    token = store.credential().get_token("https://management.azure.com/.default").token

    items = []
    for u in _usages(token):
        name_obj = u.get("name") or {}
        name = name_obj.get("value", "")
        limit, used = float(u.get("limit") or 0), float(u.get("currentValue") or 0)
        if limit <= 0 or (used <= 0 and name != "cores"):   # only limits in use, plus the regional vCPU total
            continue
        items.append({"name": name, "label": name_obj.get("localizedValue") or name,
                      "used": int(used), "limit": int(limit), "pct": round(used / limit * 100, 1)})
    items.sort(key=lambda i: -i["pct"])

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = [
        # No numbers in the title and the time is the day, so a re-run overwrites instead of duplicating.
        timeline.make_event(
            event_type="quota", severity="warning", source="quota",
            title=f"Quota: {i['label']} is at its limit" if i["pct"] >= 100 else f"Quota: {i['label']} is near its limit",
            timestamp=day_start, resource_name="subscription",
            details={"region": REGION, "used": i["used"], "limit": i["limit"], "percent": i["pct"]},
        )
        for i in items if i["pct"] >= WARN_PCT
    ]

    snapshot = {"id": f"quota-{stamp}", "type": "quota", "timestamp": timeline.iso(now), "day": now.strftime("%Y-%m-%d"),
                "region": REGION, "count": len(items), "items": items}
    store.upsert("snapshots", snapshot)
    for event in events:
        store.upsert("events", event)
    blob_path = f"quota/{now:%Y-%m-%d}/{now:%H%M%S}.json"
    store.archive_json(blob_path, snapshot)
    store.upsert("snapshots", {**snapshot, "id": "quota-latest"})
    return {"snapshotId": snapshot["id"], "limits": len(items), "events": len(events), "blob": f"raw-snapshots/{blob_path}"}