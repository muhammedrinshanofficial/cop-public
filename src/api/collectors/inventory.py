from collections import Counter

from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from shared import config, store, timeline

QUERY = """
resources
| project id = tolower(id), name, type = tolower(type), location,
          resourceGroup = tolower(resourceGroup), kind, tags,
          skuName = tostring(sku.name)
"""


def _query_resource_graph() -> list[dict]:
    client = ResourceGraphClient(store.credential())
    rows: list[dict] = []
    skip_token = None
    while True:
        options = QueryRequestOptions(result_format="objectArray", top=1000, skip_token=skip_token)
        request = QueryRequest(subscriptions=[config.subscription_id()], query=QUERY, options=options)
        result = client.resources(request)
        rows.extend(result.data)
        skip_token = result.skip_token
        if not skip_token:
            break
    return rows


def _diff_events(previous: dict, current: list[dict], now) -> list[dict]:
    old = {r["id"]: r for r in previous.get("resources", [])}
    new = {r["id"]: r for r in current}
    events = []
    for rid, r in new.items():
        if rid not in old:
            events.append(timeline.make_event(
                event_type="change",
                severity="info",
                source="resource-graph",
                title=f"Resource added: {r['name']} ({r['type']})",
                timestamp=now,
                resource_id=rid,
                resource_name=r["name"],
                resource_group=r.get("resourceGroup", ""),
                details={"action": "added", "type": r["type"], "location": r.get("location")},
            ))
    for rid, r in old.items():
        if rid not in new:
            events.append(timeline.make_event(
                event_type="change",
                severity="warning",
                source="resource-graph",
                title=f"Resource removed: {r['name']} ({r['type']})",
                timestamp=now,
                resource_id=rid,
                resource_name=r["name"],
                resource_group=r.get("resourceGroup", ""),
                details={"action": "removed", "type": r["type"], "location": r.get("location")},
            ))
    return events


def collect() -> dict:
    now = timeline.utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    rows = _query_resource_graph()

    snapshot = {
        "id": f"inventory-{stamp}",
        "type": "inventory",
        "timestamp": timeline.iso(now),
        "day": now.strftime("%Y-%m-%d"),
        "count": len(rows),
        "byType": dict(Counter(r["type"] for r in rows)),
        "resources": rows,
    }

    previous = store.read_item("snapshots", "inventory-latest", "inventory")
    events = _diff_events(previous, rows, now) if previous else []

    store.upsert("snapshots", snapshot)
    for event in events:
        store.upsert("events", event)
    blob_path = f"inventory/{now:%Y-%m-%d}/{now:%H%M%S}.json"
    store.archive_json(blob_path, snapshot)
    store.upsert("snapshots", {**snapshot, "id": "inventory-latest"})

    return {
        "snapshotId": snapshot["id"],
        "resources": len(rows),
        "events": len(events),
        "firstRun": previous is None,
        "blob": f"raw-snapshots/{blob_path}",
    }