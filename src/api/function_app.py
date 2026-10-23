import base64
import json
import logging
import time
from datetime import datetime, timezone

import azure.functions as func

from collectors import activity, alerts, cost, forecast, inventory, metrics, quota, security, utilization, waste
from assistant import briefing, chat
from readers import views

app = func.FunctionApp()

def _json(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload), status_code=status, mimetype="application/json",
                             headers={"Cache-Control": "no-store"})


def _number(value: str | None, default: int, low: int, high: int) -> int:
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return default


def _read(handler, *args, **kwargs) -> func.HttpResponse:
    try:
        return _json(handler(*args, **kwargs))
    except Exception as exc:
        logging.exception("Read endpoint failed")
        return _json({"error": type(exc).__name__, "message": str(exc)}, 500)

@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    body = {"status": "ok", "service": "cop-api", "time": datetime.now(timezone.utc).isoformat()}
    return func.HttpResponse(json.dumps(body), mimetype="application/json")


@app.timer_trigger(schedule="0 */10 * * * *", arg_name="timer", run_on_startup=False)
def collect_inventory_timer(timer: func.TimerRequest) -> None:
    summary = inventory.collect()
    logging.info("Inventory collected: %s", summary)


@app.route(route="collect/inventory", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def collect_inventory_now(req: func.HttpRequest) -> func.HttpResponse:
    try:
        summary = inventory.collect()
        return func.HttpResponse(json.dumps(summary), mimetype="application/json")
    except Exception as exc:
        logging.exception("Inventory collection failed")
        body = {"error": type(exc).__name__, "message": str(exc)}
        return func.HttpResponse(json.dumps(body), status_code=500, mimetype="application/json")



@app.timer_trigger(schedule="0 30 2 * * *", arg_name="timer", run_on_startup=False)
def collect_cost_timer(timer: func.TimerRequest) -> None:
    summary = cost.collect()
    logging.info("Cost collected: %s", summary)


@app.route(route="collect/cost", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def collect_cost_now(req: func.HttpRequest) -> func.HttpResponse:
    try:
        summary = cost.collect()
        return func.HttpResponse(json.dumps(summary), mimetype="application/json")
    except Exception as exc:
        logging.exception("Cost collection failed")
        body = {"error": type(exc).__name__, "message": str(exc)}
        return func.HttpResponse(json.dumps(body), status_code=500, mimetype="application/json")


@app.timer_trigger(schedule="0 15 * * * *", arg_name="timer", run_on_startup=False)
def collect_metrics_timer(timer: func.TimerRequest) -> None:
    summary = metrics.collect()
    logging.info("Metrics collected: %s", summary)


@app.route(route="collect/metrics", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def collect_metrics_now(req: func.HttpRequest) -> func.HttpResponse:
    try:
        summary = metrics.collect()
        return func.HttpResponse(json.dumps(summary), mimetype="application/json")
    except Exception as exc:
        logging.exception("Metrics collection failed")
        body = {"error": type(exc).__name__, "message": str(exc)}
        return func.HttpResponse(json.dumps(body), status_code=500, mimetype="application/json")


@app.timer_trigger(schedule="0 */10 * * * *", arg_name="timer", run_on_startup=False)
def collect_activity_timer(timer: func.TimerRequest) -> None:
    summary = activity.collect()
    logging.info("Activity log collected: %s", summary)


@app.route(route="collect/activity", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def collect_activity_now(req: func.HttpRequest) -> func.HttpResponse:
    try:
        days = min(max(int(req.params.get("days", "2")), 1), 30)
        summary = activity.collect(days)
        return func.HttpResponse(json.dumps(summary), mimetype="application/json")
    except Exception as exc:
        logging.exception("Activity log collection failed")
        body = {"error": type(exc).__name__, "message": str(exc)}
        return func.HttpResponse(json.dumps(body), status_code=500, mimetype="application/json")


@app.timer_trigger(schedule="0 */10 * * * *", arg_name="timer", run_on_startup=False)
def collect_alerts_timer(timer: func.TimerRequest) -> None:
    summary = alerts.collect()
    logging.info("Alerts collected: %s", summary)


@app.route(route="collect/alerts", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def collect_alerts_now(req: func.HttpRequest) -> func.HttpResponse:
    try:
        summary = alerts.collect()
        return func.HttpResponse(json.dumps(summary), mimetype="application/json")
    except Exception as exc:
        logging.exception("Alert collection failed")
        body = {"error": type(exc).__name__, "message": str(exc)}
        return func.HttpResponse(json.dumps(body), status_code=500, mimetype="application/json")


@app.timer_trigger(schedule="0 0 3 * * *", arg_name="timer", run_on_startup=False)
def collect_utilization_timer(timer: func.TimerRequest) -> None:
    summary = utilization.collect()
    logging.info("VM utilization collected: %s", summary)


@app.route(route="collect/utilization", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def collect_utilization_now(req: func.HttpRequest) -> func.HttpResponse:
    try:
        summary = utilization.collect()
        return func.HttpResponse(json.dumps(summary), mimetype="application/json")
    except Exception as exc:
        logging.exception("VM utilization collection failed")
        body = {"error": type(exc).__name__, "message": str(exc)}
        return func.HttpResponse(json.dumps(body), status_code=500, mimetype="application/json")


@app.timer_trigger(schedule="0 30 3 * * *", arg_name="timer", run_on_startup=False)
def collect_waste_timer(timer: func.TimerRequest) -> None:
    summary = waste.collect()
    logging.info("Waste detection finished: %s", summary)


@app.route(route="collect/waste", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def collect_waste_now(req: func.HttpRequest) -> func.HttpResponse:
    try:
        summary = waste.collect()
        return func.HttpResponse(json.dumps(summary), mimetype="application/json")
    except Exception as exc:
        logging.exception("Waste detection failed")
        body = {"error": type(exc).__name__, "message": str(exc)}
        return func.HttpResponse(json.dumps(body), status_code=500, mimetype="application/json")


@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False)
def collect_security_timer(timer: func.TimerRequest) -> None:
    summary = security.collect()
    logging.info("Security scan finished: %s", summary)


@app.route(route="collect/security", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def collect_security_now(req: func.HttpRequest) -> func.HttpResponse:
    try:
        summary = security.collect()
        return func.HttpResponse(json.dumps(summary), mimetype="application/json")
    except Exception as exc:
        logging.exception("Security scan failed")
        body = {"error": type(exc).__name__, "message": str(exc)}
        return func.HttpResponse(json.dumps(body), status_code=500, mimetype="application/json")


@app.timer_trigger(schedule="0 45 2 * * *", arg_name="timer", run_on_startup=False)
def collect_forecast_timer(timer: func.TimerRequest) -> None:
    summary = forecast.collect()
    logging.info("Cost forecast finished: %s", summary)


@app.route(route="collect/forecast", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def collect_forecast_now(req: func.HttpRequest) -> func.HttpResponse:
    try:
        summary = forecast.collect()
        return func.HttpResponse(json.dumps(summary), mimetype="application/json")
    except Exception as exc:
        logging.exception("Cost forecast failed")
        body = {"error": type(exc).__name__, "message": str(exc)}
        return func.HttpResponse(json.dumps(body), status_code=500, mimetype="application/json")


# Read endpoints for the dashboard. ANONYMOUS here on purpose: the Function App's own sign-in layer
# (Step 13A) only lets requests through that come via the Static Web App.
@app.route(route="overview", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def api_overview(req: func.HttpRequest) -> func.HttpResponse:
    return _read(views.overview)


@app.route(route="inventory", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def api_inventory(req: func.HttpRequest) -> func.HttpResponse:
    return _read(views.inventory)


@app.route(route="cost", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def api_cost(req: func.HttpRequest) -> func.HttpResponse:
    only = [g.strip().lower() for g in req.params.get("groups", "").split(",") if g.strip()]
    return _read(views.cost, only=only or None)


@app.route(route="metrics", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def api_metrics(req: func.HttpRequest) -> func.HttpResponse:
    return _read(views.metrics)


@app.route(route="utilization", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def api_utilization(req: func.HttpRequest) -> func.HttpResponse:
    return _read(views.utilization)


@app.route(route="security", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def api_security(req: func.HttpRequest) -> func.HttpResponse:
    return _read(views.security)


@app.timer_trigger(schedule="0 5 * * * *", arg_name="timer", run_on_startup=False)
def collect_quota_timer(timer: func.TimerRequest) -> None:
    logging.info("Quota collected: %s", quota.collect())


@app.route(route="quota", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def api_quota(req: func.HttpRequest) -> func.HttpResponse:
    return _read(views.quota)


@app.route(route="alerts", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def api_alerts(req: func.HttpRequest) -> func.HttpResponse:
    return _read(views.alerts, days=_number(req.params.get("days"), 30, 1, 30))


@app.route(route="timeline", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def api_timeline(req: func.HttpRequest) -> func.HttpResponse:
    p = req.params
    return _read(views.timeline_events,
                 days=_number(p.get("days"), 7, 1, 30), event_type=p.get("type", ""),
                 severity=p.get("severity", ""), resource=p.get("resource", ""),
                 search=p.get("search", ""), limit=_number(p.get("limit"), 200, 1, 500))


def _user_id(req: func.HttpRequest) -> str:
    """The signed-in user, from the header the Static Web App adds. Falls back to one shared id if it is missing."""
    try:
        principal = json.loads(base64.b64decode(req.headers.get("x-ms-client-principal", "")))
        return str(principal.get("userId") or principal.get("userDetails") or "dashboard-user")
    except Exception:
        return "dashboard-user"


# The assistant is behind the dashboard sign-in like the read endpoints (it is not in the excluded path list).
@app.route(route="assistant/chat", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def api_assistant_chat(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _json({"error": "BadRequest", "message": 'Send JSON like {"question": "..."}'}, 400)
    try:
        result = chat.ask(_user_id(req), str(body.get("question", "")), str(body.get("conversationId", ""))[:40])
        return _json(result)
    except ValueError as exc:
        return _json({"error": "BadRequest", "message": str(exc)}, 400)
    except Exception as exc:
        logging.exception("Assistant failed")
        return _json({"error": type(exc).__name__, "message": "The assistant could not answer. " + str(exc)[:300]}, 502)


@app.route(route="briefing", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def api_briefing(req: func.HttpRequest) -> func.HttpResponse:
    return _read(briefing.latest)


# Behind the dashboard sign-in. A repeat press within five minutes returns the saved briefing, so it cannot be spammed.
@app.route(route="briefing/generate", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def api_briefing_generate(req: func.HttpRequest) -> func.HttpResponse:
    return _read(briefing.generate)


@app.timer_trigger(schedule="0 0 4 * * *", arg_name="timer", run_on_startup=False)
def briefing_timer(timer: func.TimerRequest) -> None:
    doc = briefing.generate(force=True)
    logging.info("Daily briefing written: %s", doc["status"])


# "Scan now" buttons on the dashboard. Behind the dashboard sign-in like the read endpoints.
# Only these four collectors, and a short cooldown per collector so the button cannot be spammed.
SCANNERS = {"security": security.collect, "inventory": inventory.collect,
            "activity": activity.collect, "alerts": alerts.collect, "quota": quota.collect}
SCAN_COOLDOWN_SECONDS = 20
_last_scan: dict = {}


@app.route(route="scan/{name}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def api_scan(req: func.HttpRequest) -> func.HttpResponse:
    name = req.route_params.get("name", "")
    scanner = SCANNERS.get(name)
    if scanner is None:
        return _json({"error": "BadRequest", "message": "Unknown scan."}, 400)
    wait = SCAN_COOLDOWN_SECONDS - (time.monotonic() - _last_scan.get(name, -1e9))
    if wait > 0:
        return _json({"error": "TooManyRequests", "message": f"This scan just ran. Try again in {int(wait) + 1} seconds."}, 429)
    _last_scan[name] = time.monotonic()
    try:
        return _json({"scan": name, "summary": scanner()})
    except Exception as exc:
        logging.exception("Scan %s failed", name)
        return _json({"error": type(exc).__name__, "message": str(exc)[:300]}, 500)