"""Federal Funds Matchmaker web server (Flask): JSON API under /api/* plus the HTML/CSS/JS site in web/static.

    Development:  flask --app web.server run --port 8000 --debug
    Production:   gunicorn -c web/gunicorn.conf.py web.server:app

Every endpoint that accepts typed text screens it on the server with the privacy filter before it is used,
saved, sent to an AI model or put into a download. Blocked text returns HTTP 422 and is never stored.
"""
import json
import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_compress import Compress
from werkzeug.exceptions import HTTPException

from agency_profiles import loader
from web.service import Engine, PrivacyBlocked

log = logging.getLogger("web")
ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
PAGES = {"", "index.html", "decisions.html", "evaluation.html", "method.html"}
ID = re.compile(r"^\d{1,12}$")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' data: https://fonts.gstatic.com; "
       "img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
       "form-action 'self'; object-src 'none'")

app = Flask(__name__, static_folder=None)
app.config.update(MAX_CONTENT_LENGTH=64 * 1024, JSON_SORT_KEYS=False,
                  COMPRESS_MIMETYPES=["application/json", "text/html", "text/css", "application/javascript",
                                      "text/javascript", "image/svg+xml"], COMPRESS_MIN_SIZE=600)
Compress(app)
engine = Engine()


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ---------------------------------------------------------------------------------------- plumbing
WRITES_PER_MINUTE = int(os.getenv("WRITES_PER_MINUTE", "120"))
_writes: dict[str, deque] = defaultdict(deque)
_writes_lock = threading.Lock()


@app.before_request
def note_activity():
    if request.path.startswith("/api/"):
        engine.touch()


@app.before_request
def limit_writes():
    """Per-address limit on POSTs (decisions, surveys, searches, briefs). Generous for people, stops scripts."""
    if request.method != "POST" or not request.path.startswith("/api/"):
        return None
    # Azure's ingress APPENDS the real client address, so the last entry is trustworthy; earlier ones can be faked
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[-1].strip()
    now = time.monotonic()
    with _writes_lock:
        q = _writes[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= WRITES_PER_MINUTE:
            return jsonify(message="Too many requests in a minute. Please wait a moment and try again."), 429
        q.append(now)
        if len(_writes) > 5000:  # forget idle addresses so memory stays flat
            for k in [k for k, v in _writes.items() if not v or now - v[-1] > 60]:
                _writes.pop(k, None)
    return None

@app.after_request
def security_headers(resp: Response):
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    path = request.path
    if path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    elif path.endswith((".css", ".js", ".svg")):
        # pages link CSS/JS with ?v=<content hash>, so a versioned file can be cached for a year
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if request.args.get("v") else "public, max-age=300"
    elif resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.errorhandler(PrivacyBlocked)
def privacy_blocked(exc: PrivacyBlocked):
    return jsonify(blocked=True, field=exc.field, message=exc.message), 422


@app.errorhandler(ApiError)
def api_error(exc: ApiError):
    return jsonify(message=exc.message), exc.status


@app.errorhandler(HTTPException)
def http_error(exc: HTTPException):
    if request.path.startswith("/api/"):
        return jsonify(message=exc.description or exc.name), exc.code
    return exc


@app.errorhandler(Exception)
def unexpected(exc: Exception):
    log.exception("Unhandled error on %s", request.path)
    return jsonify(message="Something went wrong on the server. Please try again."), 500


def agency(agency_id: str) -> str:
    if agency_id not in loader.load_all():
        raise ApiError(404, "Unknown agency")
    return agency_id


def opp(opp_id: str) -> str:
    if not ID.match(opp_id or ""):
        raise ApiError(400, "Invalid opportunity id")
    return opp_id


def body() -> dict:
    data = request.get_json(silent=True)
    if data is None and request.data:
        raise ApiError(400, "Request body must be JSON")
    if data is not None and not isinstance(data, dict):
        raise ApiError(400, "Request body must be a JSON object")
    return data or {}


def call(fn, *args):
    try:
        return fn(*args)
    except (PrivacyBlocked, ApiError, json.JSONDecodeError):
        raise  # a damaged data file is a server problem (500), not the user's input
    except KeyError:
        raise ApiError(404, "Not found")
    except ValueError as e:
        raise ApiError(400, str(e))


# ---------------------------------------------------------------------------------------- API
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    return call(engine.meta)


@app.get("/api/survey/<agency_id>")
def get_survey(agency_id):
    return call(engine.survey_payload, agency(agency_id))


@app.post("/api/survey/<agency_id>")
def post_survey(agency_id):
    return call(engine.save_survey, agency(agency_id), body())


@app.post("/api/survey/<agency_id>/reset")
def reset_survey(agency_id):
    return call(engine.reset_survey, agency(agency_id))


@app.get("/api/matches/<agency_id>")
def matches(agency_id):
    return call(engine.matches, agency(agency_id))


@app.get("/api/opportunity/<agency_id>/<opp_id>")
def opportunity(agency_id, opp_id):
    return call(engine.opportunity, agency(agency_id), opp(opp_id))


@app.post("/api/missed/<agency_id>")
def report_missed(agency_id):
    return call(engine.report_missed, agency(agency_id), str(body().get("grant") or ""))


@app.get("/api/alerts/<agency_id>")
def alerts(agency_id):
    return call(engine.alerts, agency(agency_id))


@app.get("/api/alerts/<agency_id>/calendar.ics")
def alerts_calendar(agency_id):
    data = call(engine.alerts_calendar, agency(agency_id))
    return Response(data, mimetype="text/calendar", headers={
        "Content-Disposition": f'attachment; filename="grant-deadlines-{agency_id}.ics"'})


@app.post("/api/brief/<agency_id>/<opp_id>")
def brief_download(agency_id, opp_id):
    b = body()
    fmt = "pdf" if b.get("format") == "pdf" else "text"
    data, privacy = call(engine.brief_file, agency(agency_id), opp(opp_id), str(b.get("notes") or "")[:1000], fmt)
    if fmt == "pdf":
        return Response(data, mimetype="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="brief_{opp_id}.pdf"',
            "X-Privacy-Summary": privacy["summary"][:200].encode("ascii", "ignore").decode()})
    return {"text": data, "privacy": privacy}


@app.post("/api/decision/<agency_id>/<opp_id>")
def decision(agency_id, opp_id):
    return call(engine.decide, agency(agency_id), opp(opp_id), body())


@app.get("/api/decisions/<agency_id>")
def decisions(agency_id):
    return call(engine.decisions, agency(agency_id))


@app.post("/api/decisions/<agency_id>/clear")
def clear_decisions(agency_id):
    if body().get("confirm") != "CLEAR":
        raise ApiError(400, 'To clear decisions, send {"confirm": "CLEAR"}.')
    return call(engine.clear_decisions, agency(agency_id))


@app.post("/api/decisions/<agency_id>/restore")
def restore_decisions(agency_id):
    """Undo the last clear. Clearing is unauthenticated by design (no sign-in), so it must always be reversible."""
    return call(engine.restore_decisions, agency(agency_id))


@app.post("/api/search/<agency_id>")
def search(agency_id):
    return call(engine.search, agency(agency_id), str(body().get("q") or ""))


@app.get("/api/evaluation/<agency_id>")
def evaluation(agency_id):
    return call(engine.evaluation, agency(agency_id))


@app.post("/api/evaluation/<agency_id>/run")
def evaluation_run(agency_id):
    return call(engine.start_evaluation, agency(agency_id))


@app.post("/api/evaluation/control")
def evaluation_control():
    action = str(body().get("action") or "")
    if action not in ("pause", "resume", "stop"):
        raise ApiError(400, 'Send {"action": "pause" | "resume" | "stop"}.')
    return call(engine.control_evaluation, action)


@app.post("/api/refresh")
def refresh():
    return call(engine.run_refresh)


@app.route("/api/", defaults={"rest": ""})
@app.route("/api/<path:rest>")
def api_unknown(rest):
    raise ApiError(404, "Unknown API endpoint")


# ---------------------------------------------------------------------------------------- site
@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def site(path):
    """Serve the five HTML pages and their CSS/JS. Clean URLs (/decisions) also work."""
    name = path.strip("/")
    if name and "." not in name and f"{name}.html" in PAGES:
        name = f"{name}.html"
    if name in PAGES:
        return send_from_directory(STATIC, name or "index.html")
    target = (STATIC / name).resolve()
    if STATIC.resolve() in target.parents and target.is_file():
        return send_from_directory(STATIC, name)
    return Response(NOT_FOUND, status=404, mimetype="text/html")


NOT_FOUND = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Page not found · Federal Funds Matchmaker</title><link rel="stylesheet" href="/stylesheet.css"></head>
<body><main class="container" style="min-height:100vh;display:grid;place-items:center;text-align:center">
<div><p class="page-label">404</p><h1>This page doesn't exist.</h1><p><a class="primary-button" href="/">Back to matches</a></p></div></main></body></html>"""
