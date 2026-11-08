#!/usr/bin/env bash
# Federal Funds Matchmaker: create (or reuse) every Azure resource and deploy.
#   Blob Storage (data) · Azure OpenAI (optional) · Container Registry · Container Apps environment
#   Container App (web UI, port 8000) · Container Apps Job (daily Grants.gov refresh, 6 AM ET)
#
# Run from the ROOT of this repo in Azure Cloud Shell (Bash) or a VS Code terminal after `az login`:
#     bash deploy/azure_setup.sh
# Already ran the earlier version? Copy its deploy/azure_names.env into this repo's deploy/ folder first,
# and this script reuses those resources instead of creating new ones.
# Options:
#     SKIP_OPENAI=1                        deploy without Azure OpenAI (rules + TF-IDF mode)
#     AOAI_ENDPOINT=... AOAI_KEY=... SKIP_OPENAI=1   use Azure OpenAI the organizers gave you
#     CHAT_MODELS="gpt-4.1-mini"           force a chat model
set -euo pipefail
cd "$(dirname "$0")/.."

NAMES_FILE="deploy/azure_names.env"
if [ -f "$NAMES_FILE" ]; then
  # shellcheck disable=SC1090
  source "$NAMES_FILE"; echo "Reusing resource names from $NAMES_FILE (SUFFIX=$SUFFIX)"
else
  PREFIX="${PREFIX:-ffm}"; LOCATION="${LOCATION:-eastus2}"; SUFFIX="${SUFFIX:-$RANDOM}"
  cat > "$NAMES_FILE" <<EOF
PREFIX=$PREFIX
LOCATION=$LOCATION
SUFFIX=$SUFFIX
RG=rg-$PREFIX-team
STORAGE=st${PREFIX}${SUFFIX}
AOAI=aoai-$PREFIX-$SUFFIX
ACR=acr${PREFIX}${SUFFIX}
CAE=cae-$PREFIX
APP=app-$PREFIX-web
JOB=job-$PREFIX-refresh
EOF
  # shellcheck disable=SC1090
  source "$NAMES_FILE"; echo "Created $NAMES_FILE (SUFFIX=$SUFFIX). Share it with your team (no secrets inside)."
fi
TAG="v$(date +%Y%m%d%H%M)"
IMAGE="$ACR.azurecr.io/ffm:$TAG"

echo "== Subscription"; az account show --query "{name:name, id:id}" -o table

echo "== 1. Providers + resource group"
az extension add --name containerapp --upgrade --only-show-errors
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry Microsoft.Storage Microsoft.CognitiveServices; do
  az provider register --namespace "$ns" --wait
done
az group create -n "$RG" -l "$LOCATION" -o none

echo "== 2. Blob Storage (all app data: profiles, pulls, decisions, evaluation)"
az storage account show -n "$STORAGE" -g "$RG" -o none 2>/dev/null || \
  az storage account create -n "$STORAGE" -g "$RG" -l "$LOCATION" --sku Standard_LRS --kind StorageV2 \
    --min-tls-version TLS1_2 --allow-blob-public-access false -o none
STORAGE_CONN=$(az storage account show-connection-string -n "$STORAGE" -g "$RG" --query connectionString -o tsv 2>/dev/null)
az storage container create --name ffm-data --connection-string "$STORAGE_CONN" -o none

echo "== 3. Azure OpenAI"
if [ "${SKIP_OPENAI:-0}" != "1" ]; then
  az cognitiveservices account show -n "$AOAI" -g "$RG" -o none 2>/dev/null || \
    az cognitiveservices account create -n "$AOAI" -g "$RG" -l "$LOCATION" --kind OpenAI --sku S0 --custom-domain "$AOAI" --yes -o none
  az cognitiveservices account deployment show -n "$AOAI" -g "$RG" --deployment-name embed -o none 2>/dev/null || \
    az cognitiveservices account deployment create -n "$AOAI" -g "$RG" --deployment-name embed \
      --model-name text-embedding-3-small --model-version 1 --model-format OpenAI --sku-name GlobalStandard --sku-capacity 50 -o none \
    || echo "!! embedding deployment failed (similarity will use TF-IDF)"
  if az cognitiveservices account deployment show -n "$AOAI" -g "$RG" --deployment-name chat -o none 2>/dev/null; then
    echo "chat deployment already exists"
  else
    MODELS_JSON=$(az cognitiveservices account list-models -n "$AOAI" -g "$RG" -o json)
    CHAT_OK=0
    for NAME in ${CHAT_MODELS:-gpt-4.1-mini gpt-5-mini gpt-5.1-mini gpt-4.1-nano gpt-5-nano gpt-4o-mini}; do
      VERSIONS=$(echo "$MODELS_JSON" | python3 -c "import json,sys; n=sys.argv[1]; m=json.load(sys.stdin); print(' '.join(sorted({x.get('version','') for x in m if x.get('name')==n}, reverse=True)))" "$NAME")
      for VER in $VERSIONS; do
        for SKU in GlobalStandard Standard; do
          if az cognitiveservices account deployment create -n "$AOAI" -g "$RG" --deployment-name chat \
               --model-name "$NAME" --model-version "$VER" --model-format OpenAI --sku-name "$SKU" --sku-capacity 50 -o none 2>/dev/null; then
            echo "chat deployment -> $NAME ($VER, $SKU)"; CHAT_OK=1; break 3
          fi
        done
      done
    done
    [ "$CHAT_OK" = "1" ] || echo "!! No chat model could be deployed. AI explanations off; the app still works."
  fi
  AOAI_ENDPOINT=$(az cognitiveservices account show -n "$AOAI" -g "$RG" --query properties.endpoint -o tsv)
  AOAI_KEY=$(az cognitiveservices account keys list -n "$AOAI" -g "$RG" --query key1 -o tsv)
  az cognitiveservices account deployment list -n "$AOAI" -g "$RG" --query "[].{name:name, model:properties.model.name, state:properties.provisioningState}" -o table
fi
AOAI_ENDPOINT="${AOAI_ENDPOINT:-none}"
AOAI_KEY="${AOAI_KEY:-none}"          # "none" = AI off (Container Apps secrets cannot be empty)
LANGUAGE_ENDPOINT="${LANGUAGE_ENDPOINT:-none}"
LANGUAGE_KEY="${LANGUAGE_KEY:-none}"

echo "== 4. Smoke-test Grants.gov from Azure"
curl -s -X POST https://api.grants.gov/v1/api/search2 -H "Content-Type: application/json" \
  -d '{"keyword":"landslide","oppStatuses":"forecasted|posted","rows":2}' | head -c 200 || true; echo

echo "== 5. Container Registry + Container Apps environment"
az acr show -n "$ACR" -g "$RG" -o none 2>/dev/null || az acr create -n "$ACR" -g "$RG" -l "$LOCATION" --sku Basic --admin-enabled true -o none
az containerapp env show -n "$CAE" -g "$RG" -o none 2>/dev/null || az containerapp env create -n "$CAE" -g "$RG" -l "$LOCATION" -o none
ACR_USER=$(az acr credential show -n "$ACR" --query username -o tsv)
ACR_PASS=$(az acr credential show -n "$ACR" --query "passwords[0].value" -o tsv)

echo "== 6. Build the image in the cloud: $IMAGE"
az acr build --registry "$ACR" --image "ffm:$TAG" .

SECRETS=(storage-conn="$STORAGE_CONN" aoai-key="$AOAI_KEY" language-key="$LANGUAGE_KEY")
VARS=(STORAGE_CONN=secretref:storage-conn AOAI_ENDPOINT="$AOAI_ENDPOINT" AOAI_KEY=secretref:aoai-key
      AOAI_CHAT_DEPLOYMENT=chat AOAI_EMBED_DEPLOYMENT=embed LANGUAGE_ENDPOINT="$LANGUAGE_ENDPOINT"
      LANGUAGE_KEY=secretref:language-key AGENCIES=all)

echo "== 7. Web app (Container App)"
if az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  az containerapp secret set -n "$APP" -g "$RG" --secrets "${SECRETS[@]}" -o none
  az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" --set-env-vars MODE=app "${VARS[@]}" -o none
else
  az containerapp create -n "$APP" -g "$RG" --environment "$CAE" --image "$IMAGE" \
    --registry-server "$ACR.azurecr.io" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --ingress external --target-port 8000 --cpu 1.0 --memory 2.0Gi --min-replicas 1 --max-replicas 1 \
    --secrets "${SECRETS[@]}" --env-vars MODE=app "${VARS[@]}" -o none
fi

echo "== 8. Daily refresh job (10:00 UTC ≈ 5-6 AM Eastern) + run it now"
if az containerapp job show -n "$JOB" -g "$RG" -o none 2>/dev/null; then
  az containerapp job secret set -n "$JOB" -g "$RG" --secrets "${SECRETS[@]}" -o none
  az containerapp job update -n "$JOB" -g "$RG" --image "$IMAGE" --set-env-vars MODE=job "${VARS[@]}" -o none
else
  az containerapp job create -n "$JOB" -g "$RG" --environment "$CAE" --trigger-type Schedule --cron-expression "0 10 * * *" \
    --replica-timeout 3600 --replica-retry-limit 1 --replica-completion-count 1 --parallelism 1 \
    --image "$IMAGE" --registry-server "$ACR.azurecr.io" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --cpu 1.0 --memory 2.0Gi --secrets "${SECRETS[@]}" --env-vars MODE=job "${VARS[@]}" -o none
fi
az containerapp job start -n "$JOB" -g "$RG" -o none

URL="https://$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
echo
echo "=================================================================="
echo " App URL: $URL"
echo " First data refresh is running (5-15 min). Check it with:"
echo "   bash deploy/status.sh"
echo "=================================================================="
