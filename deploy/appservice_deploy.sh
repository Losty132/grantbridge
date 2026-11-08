#!/usr/bin/env bash
# OPTIONAL alternative host: run the same container on Azure App Service (Linux, B1).
# Requires deploy/azure_setup.sh to have run first (it builds the image and creates storage/OpenAI).
# The daily refresh still runs as the Container Apps Job; App Service users can also click "Refresh".
#     bash deploy/appservice_deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source deploy/azure_names.env
PLAN="plan-$PREFIX"; WEB="web-$PREFIX-$SUFFIX"
TAG=$(az acr repository show-tags -n "$ACR" --repository ffm --orderby time_desc --top 1 -o tsv)
STORAGE_CONN=$(az storage account show-connection-string -n "$STORAGE" -g "$RG" --query connectionString -o tsv)
AOAI_ENDPOINT=$(az cognitiveservices account show -n "$AOAI" -g "$RG" --query properties.endpoint -o tsv 2>/dev/null || echo none)
AOAI_KEY=$(az cognitiveservices account keys list -n "$AOAI" -g "$RG" --query key1 -o tsv 2>/dev/null || echo none)
ACR_USER=$(az acr credential show -n "$ACR" --query username -o tsv)
ACR_PASS=$(az acr credential show -n "$ACR" --query "passwords[0].value" -o tsv)
az appservice plan show -n "$PLAN" -g "$RG" -o none 2>/dev/null || az appservice plan create -n "$PLAN" -g "$RG" -l "$LOCATION" --is-linux --sku B1 -o none
az webapp show -n "$WEB" -g "$RG" -o none 2>/dev/null || \
  az webapp create -n "$WEB" -g "$RG" -p "$PLAN" --container-image-name "$ACR.azurecr.io/ffm:$TAG" \
    --container-registry-url "https://$ACR.azurecr.io" --container-registry-user "$ACR_USER" --container-registry-password "$ACR_PASS" -o none
az webapp config container set -n "$WEB" -g "$RG" --container-image-name "$ACR.azurecr.io/ffm:$TAG" \
  --container-registry-url "https://$ACR.azurecr.io" --container-registry-user "$ACR_USER" --container-registry-password "$ACR_PASS" -o none
az webapp config set -n "$WEB" -g "$RG" --web-sockets-enabled true --always-on true -o none   # Streamlit needs websockets
az webapp config appsettings set -n "$WEB" -g "$RG" -o none --settings MODE=app WEBSITES_PORT=8000 \
  STORAGE_CONN="$STORAGE_CONN" AOAI_ENDPOINT="$AOAI_ENDPOINT" AOAI_KEY="$AOAI_KEY" AOAI_CHAT_DEPLOYMENT=chat \
  AOAI_EMBED_DEPLOYMENT=embed AGENCIES=all
echo "App Service URL: https://$(az webapp show -n "$WEB" -g "$RG" --query defaultHostName -o tsv)"
