import logging
import math
from datetime import datetime, timedelta, timezone

import requests

from shared import config, store, timeline

ARM_URL = "https://management.azure.com"
LOG_ANALYTICS_URL = "https://api.loganalytics.io/v1/workspaces/{ws}/query"
VM_TYPE = "microsoft.compute/virtualmachines"

WINDOW_DAYS = 7          # how much history every run looks at
CPU_EVENT_PCT = 80.0     # a 5-minute average above this makes a timeline event

MEMORY_QUERY = """
Perf
| where ObjectName == "Memory" and CounterName in ("% Available Memory", "Available MBytes Memory")
| summarize availPct = maxif(CounterValue, CounterName == "% Available Memory"),
            availMB = maxif(CounterValue, CounterName == "Available MBytes Memory")
            by Computer, bin(TimeGenerated, 1m)
| where availPct > 0 and availMB > 0
| extend usedPct = 100.0 - availPct, usedMB = availMB / (availPct / 100.0) - availMB
| summarize avgPct = avg(usedPct), p95Pct = percentile(usedPct, 95), maxPct = max(usedPct),
            avgMB = avg(usedMB), p95MB = percentile(usedMB, 95), maxMB = max(usedMB),
            samples = count() by Computer
"""


def _token(scope: str) -> str:
    return store.credential().get_token(scope).token


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = max(math.ceil(pct / 100 * len(ordered)) - 1, 0)
    return ordered[index]


def _stats(values: list[float]) -> dict | None:
    if not values:
        return None
    return {
        "avg": round(sum(values) / len(values), 2),
        "p95": round(_percentile(values, 95), 2),
        "max": round(max(values), 2),
        "samples": len(values),
    }


def _cpu_points(vm_id: str, start: datetime, now: datetime, token: str) -> list[tuple[str, float]]:
    url = f"{ARM_URL}{vm_id}/providers/Microsoft.Insights/metrics"
    params = {
        "api-version": "2018-01-01",
        "metricnames": "Percentage CPU",
        "aggregation": "Average",
        "interval": "PT5M",
        "timespan": f"{timeline.iso(start)}/{timeline.iso(now)}",
    }
    resp = requests.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Azure Monitor returned {resp.status_code}: {resp.text[:300]}")
    points = []
    for metric in resp.json().get("value", []):
        for series in metric.get("timeseries", []):
            for p in series.get("data", []):
                if p.get("average") is not None:
                    points.append((p["timeStamp"], float(p["average"])))
    return points


def _memory_by_computer(token: str) -> dict[str, dict]:
    url = LOG_ANALYTICS_URL.format(ws=config.log_analytics_workspace_id())
    body = {"query": MEMORY_QUERY, "timespan": f"P{WINDOW_DAYS}D"}
    resp = requests.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Log Analytics returned {resp.status_code}: {resp.text[:300]}")
    result = {}
    for table in resp.json().get("tables", []):
        names = [c["name"] for c in table.get("columns", [])]
        for row in table.get("rows", []):
            r = dict(zip(names, row))
            result[str(r["Computer"]).lower()] = {
                "avgUsedPct": round(float(r["avgPct"]), 2),
                "p95UsedPct": round(float(r["p95Pct"]), 2),
                "maxUsedPct": round(float(r["maxPct"]), 2),
                "avgUsedMB": round(float(r["avgMB"]), 1),
                "p95UsedMB": round(float(r["p95MB"]), 1),
                "maxUsedMB": round(float(r["maxMB"]), 1),
                "samples": int(r["samples"]),
            }
    return result


def _cpu_events(vm: dict, points: list[tuple[str, float]]) -> list[dict]:
    peaks: dict[str, tuple[str, float]] = {}
    for ts, value in points:
        day = ts[:10]
        if day not in peaks or value > peaks[day][1]:
            peaks[day] = (ts, value)
    events = []
    for day, (peak_ts, value) in sorted(peaks.items()):
        if value < CPU_EVENT_PCT:
            continue
        # One event per VM per day, stamped with the day, so a re-run overwrites instead of duplicating.
        events.append(timeline.make_event(
            event_type="metric", severity="warning", source="azure-monitor",
            title=f"High CPU on {vm['name']} on {day}",
            timestamp=datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc),
            resource_id=vm["id"], resource_name=vm["name"], resource_group=vm.get("resourceGroup", ""),
            details={"day": day, "peakCpuPct": round(value, 2), "peakTime": peak_ts, "threshold": CPU_EVENT_PCT},
        ))
    return events


def collect() -> dict:
    now = timeline.utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    start = now - timedelta(days=WINDOW_DAYS)

    inventory = store.read_item("snapshots", "inventory-latest", "inventory")
    if not inventory:
        raise RuntimeError("No inventory snapshot yet. Run /api/collect/inventory first.")
    vms = [r for r in inventory["resources"] if r["type"] == VM_TYPE]

    memory = _memory_by_computer(_token("https://api.loganalytics.io/.default"))
    arm_token = _token("https://management.azure.com/.default")

    entries, events, errors = [], [], 0
    for vm in vms:
        cpu = None
        try:
            points = _cpu_points(vm["id"], start, now, arm_token)
            cpu = _stats([v for _, v in points])
            events.extend(_cpu_events(vm, points))
        except Exception:
            errors += 1
            logging.exception("CPU query failed for %s", vm["name"])
        entries.append({
            "resourceId": vm["id"],
            "name": vm["name"],
            "resourceGroup": vm.get("resourceGroup", ""),
            "cpuPct": cpu,
            "memory": memory.get(vm["name"].lower()),
        })

    snapshot = {
        "id": f"metrics-{stamp}",
        "type": "metrics",
        "timestamp": timeline.iso(now),
        "day": now.strftime("%Y-%m-%d"),
        "windowDays": WINDOW_DAYS,
        "vms": entries,
    }

    store.upsert("snapshots", snapshot)
    for event in events:
        store.upsert("events", event)
    blob_path = f"metrics/{now:%Y-%m-%d}/{now:%H%M%S}.json"
    store.archive_json(blob_path, snapshot)
    store.upsert("snapshots", {**snapshot, "id": "metrics-latest"})

    return {
        "snapshotId": snapshot["id"],
        "vms": len(entries),
        "withCpu": sum(1 for e in entries if e["cpuPct"]),
        "withMemory": sum(1 for e in entries if e["memory"]),
        "events": len(events),
        "errors": errors,
        "blob": f"raw-snapshots/{blob_path}",
    }