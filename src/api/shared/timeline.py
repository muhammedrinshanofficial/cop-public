import hashlib
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_event(
    *,
    event_type: str,
    severity: str,
    source: str,
    title: str,
    timestamp: datetime | None = None,
    resource_id: str = "",
    resource_name: str = "",
    resource_group: str = "",
    details: dict | None = None,
) -> dict:
    """Build one unified timeline event (the shape stored in the 'events' container)."""
    ts = timestamp or utc_now()
    rid = (resource_id or "").lower()
    key = f"{event_type}|{source}|{rid}|{title}|{iso(ts)}"
    return {
        "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:32],
        "day": ts.strftime("%Y-%m-%d"),
        "timestamp": iso(ts),
        "eventType": event_type,
        "severity": severity,
        "source": source,
        "resourceId": rid,
        "resourceName": resource_name,
        "resourceGroup": (resource_group or "").lower(),
        "title": title,
        "details": details or {},
    }


def parse_iso(value: str) -> datetime:
    """Parse an Azure timestamp such as 2026-10-14T10:21:35.1234567Z into a UTC datetime (whole seconds)."""
    return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)