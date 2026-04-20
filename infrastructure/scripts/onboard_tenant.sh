#!/usr/bin/env bash
# onboard_tenant.sh — Axon Enterprise tenant onboarding
#
# Creates a fully provisioned tenant in one command:
#   1. Validates environment and CLI tools
#   2. Inserts tenant row in PostgreSQL
#   3. Creates AWS SM secrets (axon/tenants/{id}/{provider}_api_key)
#   4. Generates an Axon API key for the tenant's service account
#   5. Prints a summary with next steps
#
# Usage:
#   export DATABASE_URL="postgresql://user:pass@host:5432/axon?sslmode=require"
#   export AWS_REGION="us-east-1"                  # optional, default us-east-1
#   export AXON_API_URL="https://your-axon-server"  # optional, for key registration
#
#   ./onboard_tenant.sh --id example-tenant --name "Example Tenant" --plan enterprise
#
# Options:
#   -i | --id       Tenant slug (required, lowercase alphanumeric + hyphens)
#   -n | --name     Human-readable name (required)
#   -p | --plan     Plan: starter | pro | enterprise  (default: starter)
#   -r | --region   AWS region (default: $AWS_REGION or us-east-1)
#   -d | --dry-run  Print what would be done without executing

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────

TENANT_ID=""
TENANT_NAME=""
PLAN="starter"
AWS_REGION="${AWS_REGION:-us-east-1}"
DRY_RUN=false
PROVIDERS=("anthropic" "openai" "gemini" "openrouter" "groq")

# ── Colors ────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()   { error "$*"; exit 1; }

# ── Argument parsing ──────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--id)      TENANT_ID="$2";   shift 2 ;;
    -n|--name)    TENANT_NAME="$2"; shift 2 ;;
    -p|--plan)    PLAN="$2";        shift 2 ;;
    -r|--region)  AWS_REGION="$2";  shift 2 ;;
    -d|--dry-run) DRY_RUN=true;     shift   ;;
    *) die "Unknown option: $1" ;;
  esac
done

# ── Validation ────────────────────────────────────────────────────────────────

[[ -z "$TENANT_ID" ]]   && die "--id is required"
[[ -z "$TENANT_NAME" ]] && die "--name is required"

if ! [[ "$TENANT_ID" =~ ^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$ ]]; then
  die "--id must be lowercase alphanumeric with hyphens (2–63 chars)"
fi

if ! [[ "$PLAN" =~ ^(starter|pro|enterprise)$ ]]; then
  die "--plan must be starter, pro, or enterprise"
fi

[[ -z "${DATABASE_URL:-}" ]] && die "DATABASE_URL environment variable is required"

command -v psql  &>/dev/null || die "psql is required (install postgresql-client)"
command -v aws   &>/dev/null || die "aws CLI is required (install awscli)"

echo ""
echo -e "${BOLD}Axon Enterprise — Tenant Onboarding${RESET}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Tenant ID   : ${BOLD}${TENANT_ID}${RESET}"
echo -e "  Name        : ${TENANT_NAME}"
echo -e "  Plan        : ${PLAN}"
echo -e "  AWS Region  : ${AWS_REGION}"
echo -e "  Dry run     : ${DRY_RUN}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if $DRY_RUN; then
  warn "DRY RUN — no changes will be made"
  echo ""
fi

# ── Step 1: Insert tenant into PostgreSQL ─────────────────────────────────────

info "Step 1/3 — Inserting tenant '${TENANT_ID}' into PostgreSQL…"

SQL="
INSERT INTO tenants (tenant_id, name, plan, status, created_at, updated_at)
VALUES ('${TENANT_ID}', '${TENANT_NAME}', '${PLAN}', 'active', NOW(), NOW())
ON CONFLICT (tenant_id) DO UPDATE
  SET name       = EXCLUDED.name,
      plan       = EXCLUDED.plan,
      updated_at = NOW()
RETURNING tenant_id, plan, status, created_at;
"

if $DRY_RUN; then
  echo "  Would execute SQL:"
  echo "$SQL" | sed 's/^/    /'
else
  RESULT=$(psql "$DATABASE_URL" --tuples-only --no-align --command "$SQL" 2>&1) || \
    die "PostgreSQL insert failed: $RESULT"
  ok "Tenant '${TENANT_ID}' inserted/updated in tenants table"
  echo "  $RESULT"
fi
echo ""

# ── Step 2: Create AWS SM secrets ─────────────────────────────────────────────

info "Step 2/3 — Creating AWS Secrets Manager paths for tenant '${TENANT_ID}'…"
SM_PREFIX="axon/tenants/${TENANT_ID}"
CREATED_ARNS=()

for provider in "${PROVIDERS[@]}"; do
  SECRET_NAME="${SM_PREFIX}/${provider}_api_key"
  info "  Creating secret: ${SECRET_NAME}"

  if $DRY_RUN; then
    echo "    Would run: aws secretsmanager create-secret --name '${SECRET_NAME}'"
    continue
  fi

  # Check if secret already exists
  EXISTING=$(aws secretsmanager describe-secret \
    --secret-id "$SECRET_NAME" \
    --region "$AWS_REGION" \
    --query 'ARN' --output text 2>/dev/null || true)

  if [[ -n "$EXISTING" && "$EXISTING" != "None" ]]; then
    warn "  Secret '${SECRET_NAME}' already exists — skipping (ARN: ${EXISTING})"
    CREATED_ARNS+=("$EXISTING")
    continue
  fi

  ARN=$(aws secretsmanager create-secret \
    --name "$SECRET_NAME" \
    --description "LLM API key for Axon tenant '${TENANT_ID}' — provider '${provider}'" \
    --secret-string "" \
    --region "$AWS_REGION" \
    --tags \
      "Key=TenantId,Value=${TENANT_ID}" \
      "Key=Provider,Value=${provider}" \
      "Key=Plan,Value=${PLAN}" \
      "Key=ManagedBy,Value=onboard_tenant.sh" \
    --query 'ARN' --output text 2>&1) || \
    die "Failed to create secret '${SECRET_NAME}': $ARN"

  ok "  Created: ${SECRET_NAME}"
  CREATED_ARNS+=("$ARN")
done
echo ""

# ── Step 3: Generate Axon API key ─────────────────────────────────────────────

info "Step 3/3 — Generating Axon API key for tenant '${TENANT_ID}'…"

# Generate a cryptographically random API key using urandom
AXON_API_KEY="axon-${TENANT_ID}-$(openssl rand -hex 24 2>/dev/null || \
  head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 48)"

# Store the API key in SM so it can be retrieved later
API_KEY_SECRET="${SM_PREFIX}/axon_api_key"

if $DRY_RUN; then
  echo "  Would store Axon API key at SM path: ${API_KEY_SECRET}"
else
  EXISTING_KEY=$(aws secretsmanager describe-secret \
    --secret-id "$API_KEY_SECRET" \
    --region "$AWS_REGION" \
    --query 'ARN' --output text 2>/dev/null || true)

  if [[ -n "$EXISTING_KEY" && "$EXISTING_KEY" != "None" ]]; then
    warn "  API key secret already exists — retrieving existing key"
    AXON_API_KEY=$(aws secretsmanager get-secret-value \
      --secret-id "$API_KEY_SECRET" \
      --region "$AWS_REGION" \
      --query 'SecretString' --output text 2>/dev/null || echo "COULD_NOT_RETRIEVE")
  else
    aws secretsmanager create-secret \
      --name "$API_KEY_SECRET" \
      --description "Axon service API key for tenant '${TENANT_ID}'" \
      --secret-string "$AXON_API_KEY" \
      --region "$AWS_REGION" \
      --tags \
        "Key=TenantId,Value=${TENANT_ID}" \
        "Key=ManagedBy,Value=onboard_tenant.sh" \
      --query 'ARN' --output text >/dev/null || \
      die "Failed to store Axon API key in Secrets Manager"
    ok "  Axon API key stored at: ${API_KEY_SECRET}"
  fi
fi
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────

echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Onboarding complete: ${TENANT_ID}${RESET}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "  ${BOLD}Axon API Key:${RESET}"
echo -e "    ${AXON_API_KEY}"
echo ""
echo -e "  ${BOLD}Secrets Manager paths:${RESET}"
for provider in "${PROVIDERS[@]}"; do
  echo "    axon/tenants/${TENANT_ID}/${provider}_api_key"
done
echo "    axon/tenants/${TENANT_ID}/axon_api_key"
echo ""
echo -e "  ${BOLD}Next steps for the tenant:${RESET}"
echo "    1. Share the Axon API Key above with the tenant securely"
echo "    2. Tenant sets their LLM keys:"
echo "       aws secretsmanager put-secret-value \\"
echo "         --secret-id axon/tenants/${TENANT_ID}/anthropic_api_key \\"
echo "         --secret-string 'sk-ant-...' --region ${AWS_REGION}"
echo "    3. To suspend: UPDATE tenants SET status='suspended' WHERE tenant_id='${TENANT_ID}';"
echo ""

if $DRY_RUN; then
  warn "DRY RUN complete — no actual changes were made"
fi
