# Gunicorn settings for the Azure Container App.
# One process keeps a single in-memory cache (rankings, enrichments); threads handle concurrent requests.
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = 1
worker_class = "gthread"
threads = int(os.getenv("WEB_THREADS", "8"))
timeout = 300            # a manual "Refresh from Grants.gov" or an evaluation run can take a few minutes
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
forwarded_allow_ips = "*"


def post_worker_init(worker):
    """Score every agency in the background as soon as the worker starts, so the first visitor never waits."""
    from web.server import engine
    engine.warm()
