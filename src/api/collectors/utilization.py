import logging
import math
import re

import requests
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from shared import config, store, timeline

ARM_URL = "https://management.azure.com"
PRICES_URL = "https://prices.azure.com/api/retail/prices"
HOURS_PER_MONTH = 730

HEADROOM = 0.30          # a smaller size must still fit the p95 usage plus 30 percent
OVER_CPU_PCT = 20.0      # over-provisioned: CPU p95 below this ...
OVER_MEM_PCT = 40.0      # ... and memory p95 below this
HIGH_PCT = 85.0          # high-utilization: CPU or memory p95 at or above this
MIN_CPU_SAMPLES = 24     # 5-minute points, so 2 hours of running time
MIN_MEM_SAMPLES = 60     # 1-minute points, so 1 hour of running time

SIZE_RE = re.compile(r"^Standard_([A-Za-z]+)(\d+)([a-z]*)(?:_(v\d+))?$")

VM_QUERY = """
resources
| where type =~ "microsoft.compute/virtualmachines"
| project id = tolower(id), name, resourceGroup = tolower(resourceGroup), location,
          vmSize = tostring(properties.hardwareProfile.vmSize),
          powerState = tostring(properties.extended.instanceView.powerState.code)
"""


def _query_vms() -> list[dict]:
    client = ResourceGraphClient(store.credential())
    options = QueryRequestOptions(result_format="objectArray", top=1000)
    request = QueryRequest(subscriptions=[config.subscription_id()], query=VM_QUERY, options=options)
    return list(client.resources(request).data)


def _vm_sizes(location: str, token: str) -> dict[str, dict]:
    """vCPU count and memory of every VM size offered in a region (the fast size list, not the full SKU catalogue)."""
    try:
        url = f"{ARM_URL}/subscriptions/{config.subscription_id()}/providers/Microsoft.Compute/locations/{location}/vmSizes"
        resp = requests.get(url, params={"api-version": "2024-07-01"},
                            headers={"Authorization": f"Bearer {token}"}, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
        return {s["name"]: {"vcpus": s["numberOfCores"], "memoryMB": s["memoryInMB"]}
                for s in resp.json().get("value", [])}
    except Exception:
        logging.exception("VM size list failed for %s", location)
        return {}


def _hourly_price(size: str, location: str, currency: str, cache: dict) -> float | None:
    """Pay-as-you-go Linux price per hour from the public Azure Retail Prices API (no login needed)."""
    key = (size, location)
    if key in cache:
        return cache[key]
    price = None
    try:
        flt = (f"serviceName eq 'Virtual Machines' and armRegionName eq '{location}' "
               f"and armSkuName eq '{size}' and priceType eq 'Consumption'")
        resp = requests.get(PRICES_URL, params={"currencyCode": currency or "USD", "$filter": flt}, timeout=30)
        if resp.status_code == 200:
            prices = [
                i["retailPrice"] for i in resp.json().get("Items", [])
                if i.get("retailPrice", 0) > 0
                and "windows" not in i.get("productName", "").lower()
                and "spot" not in i.get("skuName", "").lower()
                and "low priority" not in i.get("skuName", "").lower()
            ]
            price = min(prices) if prices else None
    except Exception:
        logging.exception("Price lookup failed for %s", size)
    cache[key] = price
    return price


def _family(size: str):
    m = SIZE_RE.match(size)
    if not m:
        return None
    features = m.group(3)
    # a = AMD processor, p = Arm processor: different hardware and a different vCPU quota family,
    # so a recommendation never crosses between them.
    return (m.group(1).upper(), m.group(4) or "", "a" in features, "p" in features)


def _recommend(vm: dict, sizes: dict, cpu: dict, mem: dict, currency: str, cache: dict):
    """Cheapest smaller size in the same family that still fits the p95 usage plus headroom."""
    current = sizes.get(vm["vmSize"])
    family = _family(vm["vmSize"])
    if not current or not family:
        return None, "size details not available"
    need_vcpus = max(1, math.ceil(cpu["p95"] / 100 * current["vcpus"] * (1 + HEADROOM)))
    need_mb = (mem["p95MB"] or mem["p95"] / 100 * current["memoryMB"]) * (1 + HEADROOM)
    candidates = [
        name for name, s in sizes.items()
        if name != vm["vmSize"] and _family(name) == family
        and need_vcpus <= s["vcpus"] <= current["vcpus"]
        and need_mb <= s["memoryMB"] <= current["memoryMB"]
    ]
    if not candidates:
        return None, "no smaller size in the same family fits the usage"

    current_price = _hourly_price(vm["vmSize"], vm["location"], currency, cache)
    options = []
    for name in candidates:
        price = _hourly_price(name, vm["location"], currency, cache)
        options.append((price if price is not None else math.inf, sizes[name]["memoryMB"], sizes[name]["vcpus"], name))
    options.sort()
    price, memory_mb, vcpus, name = options[0]
    if current_price is not None and price != math.inf and price >= current_price:
        return None, "no cheaper size in the same family fits the usage"
    known = price != math.inf and current_price is not None
    return {
        "size": name,
        "vcpus": vcpus,
        "memoryMB": memory_mb,
        "hourlyPrice": None if price == math.inf else round(price, 4),
        "monthlyListPrice": None if price == math.inf else round(price * HOURS_PER_MONTH, 2),
        "estimatedMonthlySaving": round((current_price - price) * HOURS_PER_MONTH, 2) if known else None,
    }, ""

def _memory_for_size(raw: dict | None, size_mb: int | None) -> dict | None:
    """Memory used as a percentage of the VM's current size, so a resize does not distort older samples."""
    if not raw:
        return None
    if raw.get("p95UsedMB") is not None and size_mb:
        return {
            "avg": round(raw["avgUsedMB"] / size_mb * 100, 2),
            "p95": round(raw["p95UsedMB"] / size_mb * 100, 2),
            "max": round(raw["maxUsedMB"] / size_mb * 100, 2),
            "samples": raw["samples"],
            "p95MB": raw["p95UsedMB"],
        }
    return {"avg": raw["avgUsedPct"], "p95": raw["p95UsedPct"], "max": raw["maxUsedPct"],
            "samples": raw["samples"], "p95MB": None}

def _classify(cpu: dict | None, mem: dict | None) -> tuple[str, list[str]]:
    if not cpu or not mem or cpu["samples"] < MIN_CPU_SAMPLES or mem["samples"] < MIN_MEM_SAMPLES:
        return "insufficient-data", ["not enough CPU or memory samples yet (the VM must run for a few hours)"]
    reasons = []
    if cpu["p95"] >= HIGH_PCT:
        reasons.append(f"CPU p95 is {cpu['p95']}% (at or above {HIGH_PCT}%)")
    if mem["p95"] >= HIGH_PCT:
        reasons.append(f"memory p95 is {mem['p95']}% (at or above {HIGH_PCT}%)")
    if reasons:
        return "high-utilization", reasons
    if cpu["p95"] < OVER_CPU_PCT and mem["p95"] < OVER_MEM_PCT:
        return "over-provisioned", [
            f"CPU p95 is {cpu['p95']}% (below {OVER_CPU_PCT}%)",
            f"memory p95 is {mem['p95']}% (below {OVER_MEM_PCT}%)",
        ]
    return "right-sized", [f"CPU p95 {cpu['p95']}%, memory p95 {mem['p95']}%"]


def collect() -> dict:
    now = timeline.utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    metrics = store.read_item("snapshots", "metrics-latest", "metrics")
    cost = store.read_item("snapshots", "cost-latest", "cost")
    if not metrics or not cost:
        raise RuntimeError("Run /api/collect/metrics and /api/collect/cost first.")
    currency = cost.get("currency", "")
    billed = {r["resourceId"]: r["total"] for r in cost.get("byResource", [])}
    usage = {v["resourceId"].lower(): v for v in metrics.get("vms", [])}

    arm_token = store.credential().get_token("https://management.azure.com/.default").token
    vms = _query_vms()
    sizes_by_location = {loc: _vm_sizes(loc, arm_token) for loc in {v["location"] for v in vms}}
    price_cache: dict = {}
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    entries, events = [], []
    for vm in vms:
        sizes = sizes_by_location.get(vm["location"], {})
        u = usage.get(vm["id"], {})
        cpu = u.get("cpuPct")
        current = sizes.get(vm["vmSize"], {})
        mem = _memory_for_size(u.get("memory"), current.get("memoryMB"))

        status, reasons = _classify(cpu, mem)
        recommendation, note = None, ""
        if status == "over-provisioned":
            recommendation, note = _recommend(vm, sizes, cpu, mem, currency, price_cache)

        hourly = _hourly_price(vm["vmSize"], vm["location"], currency, price_cache)
        entries.append({
            "resourceId": vm["id"],
            "name": vm["name"],
            "resourceGroup": vm["resourceGroup"],
            "location": vm["location"],
            "vmSize": vm["vmSize"],
            "vcpus": current.get("vcpus"),
            "memoryMB": current.get("memoryMB"),
            "powerState": vm.get("powerState", ""),
            "cpuPct": cpu,
            "memoryUsedPct": mem,
            "billedCost30d": round(billed.get(vm["id"], 0.0), 2),
            "hourlyPrice": None if hourly is None else round(hourly, 4),
            "monthlyListPrice": None if hourly is None else round(hourly * HOURS_PER_MONTH, 2),
            "status": status,
            "reasons": reasons,
            "recommendation": recommendation,
            "recommendationNote": note,
        })

        if status in ("over-provisioned", "high-utilization"):
            label = "over-provisioned" if status == "over-provisioned" else "running hot"
            # One event per VM per day, stamped with the day, so a re-run overwrites instead of duplicating.
            events.append(timeline.make_event(
                event_type="rightsizing", severity="warning", source="right-sizing",
                title=f"Right-sizing: {vm['name']} is {label} ({vm['vmSize']})",
                timestamp=day_start, resource_id=vm["id"], resource_name=vm["name"],
                resource_group=vm["resourceGroup"],
                details={"status": status, "reasons": reasons, "cpuPct": cpu, "memoryUsedPct": mem,
                         "recommendation": recommendation, "currency": currency},
            ))

    saving = sum((e["recommendation"] or {}).get("estimatedMonthlySaving") or 0
                 for e in entries if e["status"] == "over-provisioned")
    snapshot = {
        "id": f"vm-utilization-{stamp}",
        "type": "vm-utilization",
        "timestamp": timeline.iso(now),
        "day": now.strftime("%Y-%m-%d"),
        "currency": currency,
        "windowDays": metrics.get("windowDays"),
        "potentialMonthlySaving": round(saving, 2),
        "vms": entries,
    }

    store.upsert("snapshots", snapshot)
    for event in events:
        store.upsert("events", event)
    blob_path = f"vm-utilization/{now:%Y-%m-%d}/{now:%H%M%S}.json"
    store.archive_json(blob_path, snapshot)
    store.upsert("snapshots", {**snapshot, "id": "vm-utilization-latest"})

    return {
        "snapshotId": snapshot["id"],
        "vms": len(entries),
        "overProvisioned": sum(1 for e in entries if e["status"] == "over-provisioned"),
        "highUtilization": sum(1 for e in entries if e["status"] == "high-utilization"),
        "insufficientData": sum(1 for e in entries if e["status"] == "insufficient-data"),
        "potentialMonthlySaving": snapshot["potentialMonthlySaving"],
        "currency": currency,
        "events": len(events),
        "blob": f"raw-snapshots/{blob_path}",
    }