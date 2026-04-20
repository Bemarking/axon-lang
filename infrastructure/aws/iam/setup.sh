#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  Axon Enterprise — one-time AWS bootstrap for the release pipeline.
#
#  Creates (idempotent):
#    1. GitHub OIDC identity provider (token.actions.githubusercontent.com)
#    2. IAM role   `github-actions-enterprise-publisher`
#       - trust scoped to tag pushes (v*) + master branch of this repo
#       - inline policy granting push access to one ECR repo
#    3. ECR Private repository `axon-enterprise`
#       (IMMUTABLE tags, scan-on-push)
#
#  Usage:
#      export AWS_ACCOUNT_ID=123456789012
#      export AWS_REGION=us-east-1
#      # optional overrides:
#      # export GITHUB_ORG=Bemarking
#      # export GITHUB_REPO=axon-enterprise
#      # export ROLE_NAME=github-actions-enterprise-publisher
#      # export ECR_REPO=axon-enterprise
#      ./infrastructure/aws/iam/setup.sh
#
#  Requires:  AWS CLI v2, logged in as a principal with IAM + ECR
#             admin (or at least iam:CreateRole, iam:PutRolePolicy,
#             iam:CreateOpenIDConnectProvider, ecr:CreateRepository).
#
#  Safe to re-run: every step checks for existing state before mutating.
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

# ─── required inputs ─────────────────────────────────────────────
: "${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID must be set (12-digit account id)}"
: "${AWS_REGION:?AWS_REGION must be set (e.g. us-east-1)}"

# ─── defaults ─────────────────────────────────────────────────────
GITHUB_ORG="${GITHUB_ORG:-Bemarking}"
GITHUB_REPO="${GITHUB_REPO:-axon-enterprise}"
ROLE_NAME="${ROLE_NAME:-github-actions-enterprise-publisher}"
ECR_REPO="${ECR_REPO:-axon/axon-enterprise}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRUST_TPL="${SCRIPT_DIR}/trust-policy.json.tpl"
PERM_TPL="${SCRIPT_DIR}/permission-policy.json.tpl"

# Scratch dir is cleaned up on exit regardless of success.
TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT

TRUST_JSON="${TMPDIR}/trust-policy.json"
PERM_JSON="${TMPDIR}/permission-policy.json"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ✓\033[0m %s\n' "$*"; }
skip() { printf '\033[1;33m -\033[0m %s\n' "$*"; }

# ─── 1. Render policy templates ────────────────────────────────────
log "Rendering policy templates with AWS_ACCOUNT_ID, AWS_REGION, ECR_REPO, GITHUB_ORG, GITHUB_REPO"
export AWS_ACCOUNT_ID AWS_REGION ECR_REPO GITHUB_ORG GITHUB_REPO
envsubst < "${TRUST_TPL}" > "${TRUST_JSON}"
envsubst < "${PERM_TPL}"  > "${PERM_JSON}"

# ─── 2. Ensure GitHub OIDC provider exists ────────────────────────
OIDC_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
log "Checking GitHub OIDC provider"
if aws iam get-open-id-connect-provider \
     --open-id-connect-provider-arn "${OIDC_ARN}" >/dev/null 2>&1; then
    skip "OIDC provider already exists (${OIDC_ARN})"
else
    aws iam create-open-id-connect-provider \
        --url https://token.actions.githubusercontent.com \
        --client-id-list sts.amazonaws.com \
        --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null
    ok "Created OIDC provider: ${OIDC_ARN}"
fi

# ─── 3. Create or update IAM role ─────────────────────────────────
log "Checking IAM role ${ROLE_NAME}"
if aws iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
    aws iam update-assume-role-policy \
        --role-name "${ROLE_NAME}" \
        --policy-document "file://${TRUST_JSON}" >/dev/null
    ok  "Updated trust policy on existing role ${ROLE_NAME}"
else
    aws iam create-role \
        --role-name "${ROLE_NAME}" \
        --assume-role-policy-document "file://${TRUST_JSON}" \
        --description "GitHub Actions OIDC publisher for ${GITHUB_ORG}/${GITHUB_REPO} → ECR ${ECR_REPO}" \
        --max-session-duration 3600 >/dev/null
    ok "Created role ${ROLE_NAME}"
fi

# ─── 4. Attach inline permission policy (put-role-policy is upsert) ─
log "Putting inline policy ecr-publisher on ${ROLE_NAME}"
aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name ecr-publisher \
    --policy-document "file://${PERM_JSON}" >/dev/null
ok "Inline policy ecr-publisher applied"

# ─── 5. Create ECR repository if missing ─────────────────────────
log "Checking ECR repository ${ECR_REPO} in ${AWS_REGION}"
if aws ecr describe-repositories \
     --repository-names "${ECR_REPO}" \
     --region "${AWS_REGION}" >/dev/null 2>&1; then
    skip "ECR repository ${ECR_REPO} already exists"
else
    aws ecr create-repository \
        --repository-name "${ECR_REPO}" \
        --image-scanning-configuration scanOnPush=true \
        --image-tag-mutability IMMUTABLE \
        --region "${AWS_REGION}" >/dev/null
    ok "Created ECR repository ${ECR_REPO} (IMMUTABLE tags, scan-on-push)"
fi

# ─── 6. Summary ────────────────────────────────────────────────────
ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${ROLE_NAME}"
REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

cat <<EOF

─────────────────────────────────────────────────────────────────
 Setup complete.

 Role ARN:        ${ROLE_ARN}
 ECR registry:    ${REGISTRY}
 ECR repository:  ${REGISTRY}/${ECR_REPO}

 Next step — configure GitHub repo variables
 (Settings → Secrets and variables → Actions → Variables):

   AWS_ACCOUNT_ID = ${AWS_ACCOUNT_ID}
   AWS_REGION     = ${AWS_REGION}

 Then push a tag to trigger the pipeline:

   git tag -a v1.0.0 -m "Axon Enterprise v1.0.0"
   git push origin v1.0.0
─────────────────────────────────────────────────────────────────
EOF
