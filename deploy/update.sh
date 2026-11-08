#!/usr/bin/env bash
# Rebuild after code changes and roll out to the web app AND the refresh job.
#   bash deploy/update.sh            RUN_JOB=1 bash deploy/update.sh   (also refresh data now)
# Fast path: Python packages live in a base image tagged with a hash of requirements.txt. It is built once;
# after that each deploy only adds the code (about a minute). The web app and the job are updated in parallel.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source deploy/azure_names.env
START=$(date +%s)
TAG="v$(date +%Y%m%d%H%M%S)"
REQ_HASH=$(sha256sum requirements.txt Dockerfile.base | sha256sum | cut -c1-12)
BASE="$ACR.azurecr.io/ffm-base:$REQ_HASH"

if az acr repository show-tags -n "$ACR" --repository ffm-base -o tsv 2>/dev/null | grep -qx "$REQ_HASH"; then
  echo "== Base image ffm-base:$REQ_HASH already built, skipping package install"
else
  echo "== Building base image ffm-base:$REQ_HASH (one time, about 5 minutes)"
  az acr build --registry "$ACR" --image "ffm-base:$REQ_HASH" -f Dockerfile.base .
fi

echo "== Building app image ffm:$TAG"
az acr build --registry "$ACR" --image "ffm:$TAG" --build-arg "BASE=$BASE" .
IMG="$ACR.azurecr.io/ffm:$TAG"

echo "== Rolling out (web app and refresh job in parallel)"
az containerapp update -n "$APP" -g "$RG" --image "$IMG" --min-replicas 1 \
  --set-env-vars AGENCIES=all PRECOMPUTE_TOP=5 -o none &
P1=$!
az containerapp job update -n "$JOB" -g "$RG" --image "$IMG" --set-env-vars AGENCIES=all PRECOMPUTE_TOP=5 -o none &
P2=$!
wait $P1
wait $P2
# Optional deadline alerts to Teams / Slack: ALERT_WEBHOOK_URL='https://...' bash deploy/update.sh
# The URL is stored as a Container Apps secret (not a plain environment variable).
if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
  echo "== Turning on Teams / Slack deadline alerts"
  az containerapp secret set -n "$APP" -g "$RG" --secrets alert-webhook="$ALERT_WEBHOOK_URL" -o none
  az containerapp update -n "$APP" -g "$RG" --set-env-vars ALERT_WEBHOOK_URL=secretref:alert-webhook -o none
  az containerapp job secret set -n "$JOB" -g "$RG" --secrets alert-webhook="$ALERT_WEBHOOK_URL" -o none
  az containerapp job update -n "$JOB" -g "$RG" --set-env-vars ALERT_WEBHOOK_URL=secretref:alert-webhook -o none
fi
[ "${RUN_JOB:-0}" = "1" ] && az containerapp job start -n "$JOB" -g "$RG" -o none && echo "== Data refresh started (runs in the background)"
echo "Deployed ffm:$TAG in $(( $(date +%s) - START ))s -> https://$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
