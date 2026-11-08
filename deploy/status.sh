#!/usr/bin/env bash
# Show the app URL, recent refresh-job runs, and the last lines of the app log.
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source deploy/azure_names.env
echo "App URL: https://$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
echo "Refresh job runs:"
az containerapp job execution list -n "$JOB" -g "$RG" \
  --query "[].{name:name, status:properties.status, start:properties.startTime}" -o table | head -8
echo "Recent app log:"
az containerapp logs show -n "$APP" -g "$RG" --tail 20 2>/dev/null || echo "(open the portal → Container App → Log stream)"
