#!/usr/bin/env bash
# Build, push and deploy ShopperMind to Azure Container Apps.
#
#   ./scripts/deploy-azure.sh prod centralindia
#
# Idempotent: re-running deploys new image tags over the existing infrastructure.
set -euo pipefail

ENVIRONMENT="${1:-dev}"
LOCATION="${2:-centralindia}"
RG="rg-shoppermind-${ENVIRONMENT}"
TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)"

say() { printf "\n\033[1m→ %s\033[0m\n" "$*"; }

command -v az >/dev/null || { echo "The Azure CLI is required: https://aka.ms/azure-cli"; exit 1; }
az account show >/dev/null 2>&1 || { echo "Run 'az login' first."; exit 1; }

if [[ -z "${POSTGRES_ADMIN_PASSWORD:-}" ]]; then
  echo "Set POSTGRES_ADMIN_PASSWORD before deploying — it is never stored in the repo."
  exit 1
fi

say "Resource group ${RG} in ${LOCATION}"
az group create -n "$RG" -l "$LOCATION" -o none

# First pass: create the infrastructure with placeholder images so the registry exists
# to push into. The second deployment swaps in the real ones.
say "Deploying infrastructure (this takes 10–15 minutes on a first run)"
az deployment group create \
  -g "$RG" -f infra/main.bicep \
  -p environmentName="$ENVIRONMENT" location="$LOCATION" \
     postgresAdminPassword="$POSTGRES_ADMIN_PASSWORD" \
  -o none

REGISTRY=$(az deployment group show -g "$RG" -n main --query properties.outputs.registryLoginServer.value -o tsv)
say "Registry: ${REGISTRY}"

say "Building and pushing images (tag ${TAG})"
az acr login --name "${REGISTRY%%.*}"
az acr build --registry "${REGISTRY%%.*}" --image "shoppermind-api:${TAG}" --file apps/api/Dockerfile apps/api
az acr build --registry "${REGISTRY%%.*}" --image "shoppermind-web:${TAG}" --file apps/web/Dockerfile apps/web
az acr build --registry "${REGISTRY%%.*}" --image "shoppermind-edge:${TAG}" --file edge/camera-agent/Dockerfile edge/camera-agent

say "Rolling out the new images"
az deployment group create \
  -g "$RG" -f infra/main.bicep \
  -p environmentName="$ENVIRONMENT" location="$LOCATION" \
     postgresAdminPassword="$POSTGRES_ADMIN_PASSWORD" \
     apiImage="${REGISTRY}/shoppermind-api:${TAG}" \
     webImage="${REGISTRY}/shoppermind-web:${TAG}" \
  -o none

WEB=$(az deployment group show -g "$RG" -n main --query properties.outputs.webUrl.value -o tsv)
API=$(az deployment group show -g "$RG" -n main --query properties.outputs.apiUrl.value -o tsv)

say "Deployed"
echo "  Web  ${WEB}"
echo "  API  ${API}/docs"
echo
echo "Open the web URL and register the first workspace. Anyone can sign up from there;"
echo "each signup gets its own isolated tenant."
