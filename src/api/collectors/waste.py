import logging
from datetime import timedelta

import requests
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from shared import config, store, timeline

ARM_URL = "https://management.azure.com"

IDLE_CPU_P95 = 5.0            # idle VM: CPU p95 below this ...
IDLE_CPU_MAX = 40.0           # ... and never busy (max below this) in the metrics window
MIN_CPU_SAMPLES = 24          # 5-minute points, so 2 hours of running time
STORAGE_WINDOW_DAYS = 30      # how far back storage transactions are counted
STORAGE_MAX_TRANSACTIONS = 100  # unused storage account: at most this many requests in the window
MIN_AGE_DAYS = 3              # a resource younger than this is never called unused

LABELS = {
    "idle-vm": "idle VM",
    "stopped-vm": "stopped VM that is still billed",
    "unused-storage": "unused storage account",
    "unattached-disk": "unattached disk",
    "unattached-nic": "unattached network interface",
    "unattached-public-ip": "unattached public IP",
}

STORAGE_QUERY = """
resources
| where type =~ "microsoft.storage/storageaccounts"
| project id = tolower(id), name, resourceGroup = tolower(resourceGroup),
          created = tostring(properties.creationTime)
"""
DISK_QUERY = """
resources
| where type =~ "microsoft.compute/disks"
| where tostring(properties.diskState) =~ "Unattached" and isempty(managedBy)
| project id = tolower(id), name, resourceGroup = tolower(resourceGroup),
          sizeGb = toint(properties.diskSizeGB), sku = tostring(sku.name),
          created = tostring(properties.timeCreated)
"""
NIC_QUERY = """
resources
| where type =~ "microsoft.network/networkinterfaces"
| where isempty(tostring(properties.virtualMachine.id)) and isempty(tostring(properties.privateEndpoint.id))
| project id = tolower(id), name, resourceGroup = tolower(resourceGroup),
          created = tostring(properties.timeCreated)
"""
PUBLIC_IP_QUERY = """
resources
| where type =~ "microsoft.network/publicipaddresses"
| where isempty(tostring(properties.ipConfiguration.id)) and isempty(tostring(properties.natGateway.id))
| project id = tolower(id), name, resourceGroup = tolower(resourceGroup),
          sku = tostring(sku.name), created = tostring(properties.timeCreated)
"""


def _graph(query: str) -> list[dict]:
    client = ResourceGraphClient(store.credential())
    options = QueryRequestOptions(result_format="objectArray", top=1000)
    request = QueryRequest(subscriptions=[config.subscription_id()], query=query, options=options)
    return list(client.resources(request).data)


def _age_days(created: str, now) -> float | None:
    """Age of a resource in days, or None when Azure gives no creation time."""
    if not created:
        return None
    try:
        return (now - timeline.parse_iso(created)).total_seconds() / 86400
    except ValueError:
        return None


def _old_enough(created: str, now) -> bool:
    age = _age_days(created, now)
    return age is None or age >= MIN_AGE_DAYS


def _storage_transactions(account_id: str, start, now, token: str) -> float:
    url = f"{ARM_URL}{account_id}/providers/Microsoft.Insights/metrics"
    params = {
        "api-version": "2018-01-01",
        "metricnames": "Transactions",
        "aggregation": "Total",
        "interval": "P1D",
        "timespan": f"{timeline.iso(start)}/{timeline.iso(now)}",
    }
    resp = requests.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Azure Monitor returned {resp.status_code}: {resp.text[:300]}")
    total = 0.0
    for metric in resp.json().get("value", []):
        for series in metric.get("timeseries", []):
            for p in series.get("data", []):
                total += float(p.get("total") or 0)
    return total  # an account that never received a request returns no data points, which counts as 0


def _finding(kind: str, rid: str, name: str, group: str, reason: str, billed: dict, details: dict) -> dict:
    return {
        "type": kind,
        "resourceId": rid,
        "name": name,
        "resourceGroup": group,
        "reason": reason,
        "billedCost30d": round(billed.get(rid, 0.0), 2),
        "details": details,
    }


def _vm_findings(utilization: dict, billed: dict) -> list[dict]:
    findings = []
    for vm in utilization.get("vms", []):
        rid, name, group = vm["resourceId"], vm["name"], vm["resourceGroup"]
        if vm.get("powerState") == "PowerState/stopped":
            findings.append(_finding(
                "stopped-vm", rid, name, group,
                "the VM is stopped from inside the operating system, so compute is still billed; deallocate it",
                billed, {"vmSize": vm["vmSize"], "powerState": vm["powerState"]}))
        cpu = vm.get("cpuPct")
        if cpu and cpu["samples"] >= MIN_CPU_SAMPLES and cpu["p95"] < IDLE_CPU_P95 and cpu["max"] < IDLE_CPU_MAX:
            findings.append(_finding(
                "idle-vm", rid, name, group,
                f"CPU p95 is {cpu['p95']}% and the peak is {cpu['max']}% over {utilization.get('windowDays')} days",
                billed, {"vmSize": vm["vmSize"], "cpuPct": cpu, "monthlyListPrice": vm.get("monthlyListPrice")}))
    return findings


def _storage_findings(now, billed: dict, token: str) -> list[dict]:
    findings = []
    start = now - timedelta(days=STORAGE_WINDOW_DAYS)
    for acc in _graph(STORAGE_QUERY):
        if not _old_enough(acc.get("created", ""), now):
            continue
        try:
            transactions = _storage_transactions(acc["id"], start, now, token)
        except Exception:
            logging.exception("Storage metrics failed for %s", acc["name"])
            continue
        if transactions <= STORAGE_MAX_TRANSACTIONS:
            findings.append(_finding(
                "unused-storage", acc["id"], acc["name"], acc["resourceGroup"],
                f"{int(transactions)} requests in the last {STORAGE_WINDOW_DAYS} days",
                billed, {"transactions": transactions, "windowDays": STORAGE_WINDOW_DAYS}))
    return findings


def _unattached_findings(now, billed: dict) -> list[dict]:
    findings = []
    for d in _graph(DISK_QUERY):
        if _old_enough(d.get("created", ""), now):
            findings.append(_finding("unattached-disk", d["id"], d["name"], d["resourceGroup"],
                                     "the disk is not attached to any VM", billed,
                                     {"sizeGb": d.get("sizeGb"), "sku": d.get("sku")}))
    for n in _graph(NIC_QUERY):
        if _old_enough(n.get("created", ""), now):
            findings.append(_finding("unattached-nic", n["id"], n["name"], n["resourceGroup"],
                                     "the network interface is not attached to a VM or a private endpoint",
                                     billed, {}))
    for ip in _graph(PUBLIC_IP_QUERY):
        if _old_enough(ip.get("created", ""), now):
            findings.append(_finding("unattached-public-ip", ip["id"], ip["name"], ip["resourceGroup"],
                                     "the public IP address is not associated with any resource",
                                     billed, {"sku": ip.get("sku")}))
    return findings


def collect() -> dict:
    now = timeline.utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    utilization = store.read_item("snapshots", "vm-utilization-latest", "vm-utilization")
    cost = store.read_item("snapshots", "cost-latest", "cost")
    if not utilization or not cost:
        raise RuntimeError("Run /api/collect/cost and /api/collect/utilization first.")
    billed = {r["resourceId"]: r["total"] for r in cost.get("byResource", [])}
    token = store.credential().get_token("https://management.azure.com/.default").token

    findings = (
        _vm_findings(utilization, billed)
        + _storage_findings(now, billed, token)
        + _unattached_findings(now, billed)
    )

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = [
        # One event per finding per day, stamped with the day, so a re-run overwrites instead of duplicating.
        timeline.make_event(
            event_type="waste", severity="warning", source="waste-detection",
            title=f"Waste: {LABELS[f['type']]} {f['name']}",
            timestamp=day_start, resource_id=f["resourceId"], resource_name=f["name"],
            resource_group=f["resourceGroup"],
            details={"type": f["type"], "reason": f["reason"], "billedCost30d": f["billedCost30d"],
                     "currency": cost.get("currency", "")},
        )
        for f in findings
    ]

    by_type: dict[str, int] = {}
    for f in findings:
        by_type[f["type"]] = by_type.get(f["type"], 0) + 1
    snapshot = {
        "id": f"waste-{stamp}",
        "type": "waste",
        "timestamp": timeline.iso(now),
        "day": now.strftime("%Y-%m-%d"),
        "currency": cost.get("currency", ""),
        "count": len(findings),
        "byType": by_type,
        "findings": findings,
    }

    store.upsert("snapshots", snapshot)
    for event in events:
        store.upsert("events", event)
    blob_path = f"waste/{now:%Y-%m-%d}/{now:%H%M%S}.json"
    store.archive_json(blob_path, snapshot)
    store.upsert("snapshots", {**snapshot, "id": "waste-latest"})

    return {
        "snapshotId": snapshot["id"],
        "findings": len(findings),
        "byType": by_type,
        "events": len(events),
        "blob": f"raw-snapshots/{blob_path}",
    }