# One image, two roles:
#   MODE=app     -> Flask + HTML/CSS/JS web app on port 8000 via gunicorn (default)
#   MODE=classic -> backup Streamlit app on port 8000
#   MODE=job  -> run the Grants.gov refresh once and exit (Azure Container Apps Job, daily schedule)
# BASE is the prebuilt package image from Dockerfile.base (deploy/update.sh passes it). Without it, this file still
# builds on its own from python:3.13-slim and installs the packages itself.
ARG BASE=python:3.13-slim
FROM ${BASE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MODE=app
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt --disable-pip-version-check -q && (id appuser >/dev/null 2>&1 || useradd --create-home appuser)
COPY --chown=appuser . .
USER appuser
EXPOSE 8000
CMD ["sh", "entrypoint.sh"]
