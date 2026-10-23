import calendar
import logging
from datetime import date, timedelta

import requests

from shared import config, store, timeline

ARM_URL = "https://management.azure.com"
RUN_RATE_DAYS = 7        # the daily run rate is the average of the last 7 finished days
AT_RISK_PCT = 80.0       # forecast at or above this share of the budget is at risk


def _budget(token: str) -> dict | None:
    """The monthly budget from Step 4, read from Azure so the amount lives in one place only."""
    try:
        url = f"{ARM_URL}/subscriptions/{config.subscription_id()}/providers/Microsoft.Consumption/budgets"
        resp = requests.get(url, params={"api-version": "2023-05-01"},
                            headers={"Authorization": f"Bearer {token}"}, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
        budgets = resp.json().get("value", [])
        chosen = next((b for b in budgets if b.get("name", "").startswith("budget-cop")), None)
        if chosen is None and budgets:
            chosen = budgets[0]
        if chosen is None:
            return None
        props = chosen["properties"]
        return {"name": chosen["name"], "amount": float(props["amount"]), "timeGrain": props.get("timeGrain")}
    except Exception:
        logging.exception("Budget lookup failed")
        return None


def _forecast(by_day: dict, today: date) -> dict:
    """Month-end cost: what is already billed this month plus the run rate times the days left."""
    finished = [today - timedelta(days=i) for i in range(1, RUN_RATE_DAYS + 1)]
    recent = [by_day.get(d.isoformat(), 0.0) for d in finished]
    with_data = sum(1 for d in finished if d.isoformat() in by_day)
    run_rate = sum(recent) / RUN_RATE_DAYS

    month_days = calendar.monthrange(today.year, today.month)[1]
    spent = sum(v for k, v in by_day.items() if k[:7] == today.strftime("%Y-%m") and k < today.isoformat())
    remaining = month_days - today.day + 1  # today counts as a day still to bill

    def project(daily: float) -> float:
        return round(spent + daily * remaining, 2)

    daily_series = [
        {"day": (today + timedelta(days=i)).isoformat(), "cost": round(run_rate, 2)} for i in range(remaining)
    ]
    return {
        "month": today.strftime("%Y-%m"),
        "spentThroughYesterday": round(spent, 2),
        "dailyRunRate": round(run_rate, 2),
        "daysRemaining": remaining,
        "forecastMonthEnd": project(run_rate),
        "forecastLow": project(min(recent)),
        "forecastHigh": project(max(recent)),
        "daysWithData": with_data,
        "confidence": "high" if with_data >= 6 else "medium" if with_data >= 3 else "low",
        "forecastDaily": daily_series,
    }


def collect() -> dict:
    now = timeline.utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    cost = store.read_item("snapshots", "cost-latest", "cost")
    if not cost:
        raise RuntimeError("Run /api/collect/cost first.")
    token = store.credential().get_token("https://management.azure.com/.default").token

    forecast = _forecast(cost.get("byDay", {}), now.date())
    budget = _budget(token)
    status, percent = "no-budget", None
    if budget and budget["amount"] > 0:
        percent = round(forecast["forecastMonthEnd"] / budget["amount"] * 100, 1)
        status = "over-budget" if percent > 100 else "at-risk" if percent >= AT_RISK_PCT else "on-track"

    events = []
    if status in ("over-budget", "at-risk"):
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "exceeds" if status == "over-budget" else "approaches"
        # The title has no numbers, so a re-run on the same day overwrites the event.
        events.append(timeline.make_event(
            event_type="cost", severity="warning", source="cost-forecast",
            title=f"Cost forecast: the month-end projection {label} the budget",
            timestamp=day_start, resource_name="subscription",
            details={"forecastMonthEnd": forecast["forecastMonthEnd"], "budget": budget["amount"],
                     "percentOfBudget": percent, "currency": cost.get("currency", "")},
        ))

    snapshot = {
        "id": f"cost-forecast-{stamp}",
        "type": "cost-forecast",
        "timestamp": timeline.iso(now),
        "day": now.strftime("%Y-%m-%d"),
        "currency": cost.get("currency", ""),
        "budget": budget,
        "percentOfBudget": percent,
        "status": status,
        **forecast,
    }

    store.upsert("snapshots", snapshot)
    for event in events:
        store.upsert("events", event)
    blob_path = f"cost-forecast/{now:%Y-%m-%d}/{now:%H%M%S}.json"
    store.archive_json(blob_path, snapshot)
    store.upsert("snapshots", {**snapshot, "id": "cost-forecast-latest"})

    return {
        "snapshotId": snapshot["id"],
        "month": forecast["month"],
        "spentThroughYesterday": forecast["spentThroughYesterday"],
        "dailyRunRate": forecast["dailyRunRate"],
        "forecastMonthEnd": forecast["forecastMonthEnd"],
        "status": status,
        "percentOfBudget": percent,
        "confidence": forecast["confidence"],
        "currency": snapshot["currency"],
        "events": len(events),
        "blob": f"raw-snapshots/{blob_path}",
    }