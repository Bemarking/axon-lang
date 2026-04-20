# AWS IAM bootstrap — release pipeline

One-time setup that provisions the AWS side of the enterprise release
pipeline declared in `.github/workflows/release.yml`.

## What it creates

| Resource | Purpose |
|---|---|
| GitHub OIDC identity provider | Lets Actions exchange its short-lived OIDC token for AWS STS credentials — no long-lived AWS keys stored in GitHub |
| IAM role `github-actions-enterprise-publisher` | Role the workflow assumes via OIDC. Trust is scoped to this repo's `v*` tags and the `master` branch |
| Inline policy `ecr-publisher` | Grants push access to the `axon-enterprise` ECR repo only — no wildcard, no other services |
| ECR Private repo `axon-enterprise` | Destination for the container images. `IMMUTABLE` tags (overwrites rejected) and `scanOnPush` for CVE gating |

## Run

```bash
export AWS_ACCOUNT_ID=123456789012     # your 12-digit account id
export AWS_REGION=us-east-1            # region for the ECR repo
./infrastructure/aws/iam/setup.sh
```

Optional overrides (environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `GITHUB_ORG` | `Bemarking` | GitHub organization owning the repo |
| `GITHUB_REPO` | `axon-enterprise` | Repository name |
| `ROLE_NAME` | `github-actions-enterprise-publisher` | IAM role name |
| `ECR_REPO` | `axon/axon-enterprise` | ECR repository name (account-wide `axon/<component>` convention) |

The script is idempotent — re-running it updates the trust policy and
inline permissions without recreating anything.

## After the script

Configure **repository variables** in GitHub
(Settings → Secrets and variables → Actions → Variables):

- `AWS_ACCOUNT_ID` — same value exported above
- `AWS_REGION` — same value exported above

These are variables, not secrets — they are not sensitive (the account
id is embedded in every ECR pull URL anyway), and using variables makes
them easier to audit.

## Granting pull access to enterprise customers

The publisher role above only covers **push** from CI. Customers need
**pull** access, granted via an ECR repository policy. Two patterns:

### Pattern A — customer has their own AWS account

Attach a repository policy that allows pull from their account:

```bash
aws ecr set-repository-policy \
  --repository-name axon/axon-enterprise \
  --region us-east-1 \
  --policy-text '{
    "Version": "2012-10-17",
    "Statement": [{
      "Sid": "AllowCustomerPull",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::<CUSTOMER_ACCOUNT>:root" },
      "Action": [
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:BatchCheckLayerAvailability"
      ]
    }]
  }'
```

Append additional statements per customer — the repository policy can
list many principals.

### Pattern B — customer has no AWS account

Create a dedicated IAM user with pull-only permission and deliver the
access key via your normal credential-handoff channel (for example a
1Password vault entry shared with the customer admin).

```bash
aws iam create-user --user-name axon-pull-<customer-slug>
aws iam put-user-policy \
  --user-name axon-pull-<customer-slug> \
  --policy-name ecr-pull \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      { "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
      {
        "Effect": "Allow",
        "Action": [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability"
        ],
        "Resource": "arn:aws:ecr:us-east-1:<ACCOUNT_ID>:repository/axon/axon-enterprise"
      }
    ]
  }'
aws iam create-access-key --user-name axon-pull-<customer-slug>
```

Rotate keys periodically and revoke immediately when a customer
contract ends.

## Security notes

- The publisher role's trust policy scopes `sub` to specific refs —
  a fork of this repo cannot assume the role even if someone pushes
  a `v*` tag there.
- `IMMUTABLE` tags on the ECR repo mean a tag once pushed cannot be
  overwritten; re-publishing a released version requires deleting the
  existing image explicitly, which emits a CloudTrail event.
- `scanOnPush` runs Amazon Inspector (or Trivy-equivalent) against
  every pushed image; wire up an SNS topic if you want alerts on
  CVEs found in a published version.
