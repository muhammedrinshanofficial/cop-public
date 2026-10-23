import json

from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from shared import config, store, timeline

REQUIRED_TAGS = ("project", "environment", "owner", "managedBy")
# Azure creates these itself and does not let our templates tag them.
EXEMPT_TYPES = {
    "microsoft.alertsmanagement/smartdetectoralertrules",
    "microsoft.network/networkwatchers",
}
OPEN_SOURCES = {"*", "0.0.0.0/0", "::/0", "internet", "any"}
MANAGEMENT_PORTS = (22, 3389)

NSG_QUERY = """
resources
| where type =~ "microsoft.network/networksecuritygroups"
| mv-expand rule = properties.securityRules
| where tostring(rule.properties.direction) =~ "Inbound" and tostring(rule.properties.access) =~ "Allow"
| project id = tolower(id), nsgName = name, resourceGroup = tolower(resourceGroup),
          ruleName = tostring(rule.name), priority = toint(rule.properties.priority),
          protocol = tostring(rule.properties.protocol),
          source = tostring(rule.properties.sourceAddressPrefix),
          sources = tostring(rule.properties.sourceAddressPrefixes),
          port = tostring(rule.properties.destinationPortRange),
          ports = tostring(rule.properties.destinationPortRanges)
"""
PUBLIC_IP_QUERY = """
resources
| where type =~ "microsoft.network/publicipaddresses"
| project id = tolower(id), name, resourceGroup = tolower(resourceGroup),
          address = tostring(properties.ipAddress), sku = tostring(sku.name),
          attachedTo = tolower(tostring(properties.ipConfiguration.id))
"""
PROJECT_TAG_VALUE = "azure-cloud-operations-center"
PROJECT_GROUP_QUERY = """
resourcecontainers
| where type =~ "microsoft.resources/subscriptions/resourcegroups"
| project name = tolower(name), tags
"""
TAG_QUERY = """
resources
| project id = tolower(id), name, type = tolower(type), resourceGroup = tolower(resourceGroup), tags
"""


def _graph(query: str) -> list[dict]:
    client = ResourceGraphClient(store.credential())
    options = QueryRequestOptions(result_format="objectArray", top=1000)
    request = QueryRequest(subscriptions=[config.subscription_id()], query=query, options=options)
    return list(client.resources(request).data)


def _items(value: str) -> list[str]:
    """An NSG rule keeps one value in one field and a list in another; both arrive as text."""
    value = (value or "").strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            return [str(x) for x in json.loads(value)]
        except ValueError:
            return []
    return [value]


def _covers(ports: list[str], target: int) -> bool:
    for p in ports:
        if p == "*":
            return True
        if "-" in p:
            low, _, high = p.partition("-")
            if low.isdigit() and high.isdigit() and int(low) <= target <= int(high):
                return True
        elif p.isdigit() and int(p) == target:
            return True
    return False


def _nsg_findings() -> list[dict]:
    findings = []
    for r in _graph(NSG_QUERY):
        sources = _items(r.get("source")) + _items(r.get("sources"))
        if not any(s.lower() in OPEN_SOURCES for s in sources):
            continue
        ports = _items(r.get("port")) + _items(r.get("ports"))
        all_ports = "*" in ports
        management = [p for p in MANAGEMENT_PORTS if _covers(ports, p)]
        severity = "critical" if all_ports or management else "warning"
        exposed = "all ports" if all_ports else "port " + ", ".join(ports or ["?"])
        findings.append({
            "type": "open-nsg-rule",
            "severity": severity,
            "resourceId": r["id"],
            "name": r["nsgName"],
            "resourceGroup": r["resourceGroup"],
            "reason": f"rule {r['ruleName']} allows the internet to reach {exposed}",
            "details": {"rule": r["ruleName"], "priority": r.get("priority"), "protocol": r.get("protocol"),
                        "sources": sources, "ports": ports},
        })
    return findings


def _public_ip_findings() -> list[dict]:
    return [{
        "type": "public-ip",
        "severity": "info",
        "resourceId": ip["id"],
        "name": ip["name"],
        "resourceGroup": ip["resourceGroup"],
        "reason": f"public IP {ip.get('address') or '(not assigned)'} exposes a resource to the internet",
        "details": {"address": ip.get("address"), "sku": ip.get("sku"), "attachedTo": ip.get("attachedTo")},
    } for ip in _graph(PUBLIC_IP_QUERY)]


def _tag_findings() -> list[dict]:
    # Only this project's own resource groups are checked. The subscription also holds other projects.
    project_groups = {
        g["name"] for g in _graph(PROJECT_GROUP_QUERY)
        if {str(k).lower(): v for k, v in (g.get("tags") or {}).items()}.get("project", "").lower() == PROJECT_TAG_VALUE
    }
    findings = []
    for r in _graph(TAG_QUERY):
        if r["type"] in EXEMPT_TYPES or r["resourceGroup"] not in project_groups:
            continue
        present = {str(k).lower() for k, v in (r.get("tags") or {}).items() if v}
        missing = [t for t in REQUIRED_TAGS if t.lower() not in present]
        if missing:
            findings.append({
                "type": "missing-tags",
                "severity": "info",
                "resourceId": r["id"],
                "name": r["name"],
                "resourceGroup": r["resourceGroup"],
                "reason": "missing tags: " + ", ".join(missing),
                "details": {"resourceType": r["type"], "missing": missing},
            })
    return findings


def collect() -> dict:
    now = timeline.utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    findings = _nsg_findings() + _public_ip_findings() + _tag_findings()

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = [
        # Only serious findings reach the timeline, one event per finding per day, so a re-run never duplicates.
        timeline.make_event(
            event_type="security", severity=f["severity"], source="security-scan",
            title=f"Security: {f['name']} - {f['reason']}",
            timestamp=day_start, resource_id=f["resourceId"], resource_name=f["name"],
            resource_group=f["resourceGroup"], details={"type": f["type"], **f["details"]},
        )
        for f in findings if f["severity"] in ("critical", "warning")
    ]

    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for f in findings:
        by_type[f["type"]] = by_type.get(f["type"], 0) + 1
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
    snapshot = {
        "id": f"security-{stamp}",
        "type": "security",
        "timestamp": timeline.iso(now),
        "day": now.strftime("%Y-%m-%d"),
        "count": len(findings),
        "byType": by_type,
        "bySeverity": by_severity,
        "findings": findings,
    }

    store.upsert("snapshots", snapshot)
    for event in events:
        store.upsert("events", event)
    blob_path = f"security/{now:%Y-%m-%d}/{now:%H%M%S}.json"
    store.archive_json(blob_path, snapshot)
    store.upsert("snapshots", {**snapshot, "id": "security-latest"})

    return {
        "snapshotId": snapshot["id"],
        "findings": len(findings),
        "byType": by_type,
        "bySeverity": by_severity,
        "events": len(events),
        "blob": f"raw-snapshots/{blob_path}",
    }