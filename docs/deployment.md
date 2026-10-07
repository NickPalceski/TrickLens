# Deployment guide

How TrickLens gets to AWS: the one-time bootstrap, everyday deploys,
checking a deploy end to end, and reading the logs. For what each resource
is and why, see [infrastructure](components/infrastructure.md).

← Back to the [README](../README.md) · [Architecture](ARCHITECTURE.md)

**TrickLens is live.** The one-time bootstrap below has been run; it's kept
for rebuilding from scratch in a new account. Day to day, deploying is just
pushing to `main`.

## Everyday deploys

Push to `main`. `.github/workflows/deploy.yml` then runs, strictly in order:

1. **test:** ruff, the API tests, the worker tests, the licence check;
2. **build-and-push-image:** both images (API and worker), tagged with the
   commit SHA;
3. **migrate:** `alembic upgrade head` against Neon, *before* the new code
   goes live. Every migration must therefore be backward-compatible with
   the old code (see
   [why](components/infrastructure.md#migrations-run-before-the-new-image-goes-live-never-after));
4. **terraform-apply:** points all three Lambdas at the new `image_tag`;
5. **smoke-test:** `GET /health/deep` must return 200, including the schema
   revision check.

Any push redeploys, even a docs-only one, which rebuilds the images. The
first clip after a deploy is slow once (see
[CloudWatch](#reading-the-logs)).

**Rollback:** `terraform apply -var image_tag=<previous_sha>`. ECR keeps the
last 5 images per repo, so that works for the last 5 deploys.

## Checking a deploy end to end (Postman)

A green pipeline only proves `/health/deep` passes. To prove a clip really
goes through the worker Lambda, import
[`postman/TrickLens-prod-check.postman_collection.json`](../postman/TrickLens-prod-check.postman_collection.json)
(a separate collection, so local testing can never hit prod by accident) and
run it top to bottom. It covers:
- health (expects the current Alembic revision);
- prod Cognito sign-up and confirm by emailed code (no AWS keys needed);
- login and register;
- create, upload a real clip, complete, and poll, with tests checking that
  ffprobe replaced the fake duration/fps and that `video_url`/`thumb_url`
  are CDN URLs. A stub-scored `unanalyzable` result still passes, as long
  as the media checks do;
- fetching the video and thumbnail from CloudFront.

Fill these in the collection's **Variables** tab (Current Value): the three
endpoint values come from `terraform -chdir=infra output` and aren't
committed (public repo).

| Variable | Source |
|---|---|
| `prod_base_url` | `terraform -chdir=infra output -raw api_invoke_url` |
| `prod_cdn_base_url` | `terraform -chdir=infra output -raw cdn_base_url` |
| `prod_cognito_client_id` | `terraform -chdir=infra output -raw cognito_client_id` |
| `prod_email`, `prod_password`, `prod_username` | yours; the password in Current Value only |
| `prod_confirmation_code` | the 6-digit code emailed after step 1 (check spam) |

Before step 6, pick the video file in that request's Body tab (binary).
The prod Cognito pool and Neon database are separate from local dev, so dev
test users don't exist there; sign up once.

## Reading the logs

Each Lambda logs to `/aws/lambda/tricklens-api`, `-worker` and `-rankings`
in CloudWatch (us-east-1, 14-day retention). Console: CloudWatch → *Log
groups* → the group → newest stream. CLI:

```bash
aws logs tail /aws/lambda/tricklens-worker --follow --since 30m
```

(The `tricklens-dev` IAM user used for Cognito has no CloudWatch access; use
the console or an admin profile.)

A worker run looks like:

```
[INFO] … worker: clip <id> stage A: 1 trick(s) [(1233, 1467, 1567)] | skater in 83% of samples, 0.14 of frame height | {…}
[INFO] … worker: clip <id> stage B trick 1: takeoff 1250 touchdown 1650 | pose 92%, feet vis 0.92, board 93% | {…}
[INFO] … worker: clip <id> -> analyzed
REPORT … Duration: … Max Memory Used: … Init Duration: …
```

- The **`REPORT`** line gives duration, memory and (on a cold start) init
  time: the numbers to watch against the worker's 300s / 3008MB.
- The **first** invocation after a deploy usually shows
  `INIT_REPORT … Status: timeout`. Lambda re-runs init inside the
  invocation and the clip still succeeds, just slower. It happens once per
  deploy, not on every cold start (see the
  [analyzer doc](components/analyzer.md#worker)).
- `sh: line 1: blkid: command not found`, `hostname: …` and an onnxruntime
  telemetry warning are harmless start-up noise.

## First-ever deploy (one time, by hand)

Every step below runs once, ever, on whichever machine does the first
deploy.

1. **Create the prod Neon database** (a real external account, not
   something Terraform manages). Save both connection strings as GitHub repo
   secrets `DATABASE_URL` and `ALEMBIC_DATABASE_URL`. The two drivers spell
   the TLS parameter differently, and Neon's copy-paste string is the
   psycopg/libpq form:

   | Secret | Driver | Form |
   |---|---|---|
   | `DATABASE_URL` | asyncpg (the app) | `postgresql+asyncpg://user:pass@host/db?ssl=require` |
   | `ALEMBIC_DATABASE_URL` | psycopg (Alembic) | `postgresql+psycopg://user:pass@host/db?sslmode=require` |

   asyncpg doesn't accept `sslmode` or `channel_binding`. For the asyncpg
   string, replace Neon's `sslmode=require` with `ssl=require` and drop
   `channel_binding=require`. `DATABASE_URL` is also what
   `TF_VAR_database_url` takes in every manual `terraform apply` below,
   since it's the value written into the SSM parameter the Lambdas read.
2. **Bootstrap the Terraform state backend:**
   ```bash
   ./scripts/terraform-bootstrap.sh
   ```
   Creates the S3 state bucket + DynamoDB lock table once (idempotent, same
   `aws configure` credentials Cognito's bootstrap script already needs).
3. **Create the GitHub OIDC provider + the two CI roles**
   (`tricklens-gha-deploy`, `tricklens-gha-plan`) by hand, using your own
   `aws configure` credentials. This is the one place Terraform can't
   bootstrap itself, since the very first `terraform apply` needs to run
   *as* a role that doesn't exist yet. `infra/iam.tf` defines these
   resources; create them once via the AWS CLI/console matching that file,
   then `terraform import` them into state so future policy changes go
   through Terraform like everything else. Save both role ARNs as GitHub
   secrets `AWS_DEPLOY_ROLE_ARN` / `AWS_PLAN_ROLE_ARN`, and set
   `BUDGET_EMAIL` (the budget alarm's recipient) too.

   The trust policies match GitHub's OIDC `sub` claim against
   `var.github_oidc_sub_prefix` (`infra/variables.tf`). This repo uses
   GitHub's *immutable* subject format
   (`repo:NickPalceski@128099643/TrickLens@1306046704:...`), not the plain
   `repo:owner/repo:...` most guides show. If the role can't be assumed
   ("Not authorized to perform sts:AssumeRoleWithWebIdentity"), compare the
   variable with `sub_claim_prefix` from
   `curl -s https://api.github.com/repos/NickPalceski/TrickLens/actions/oidc/customization/sub`.
4. **Bootstrap both ECR repos, then a first image in each** (a genuine
   Terraform chicken-and-egg: a Lambda container function needs its image
   to already exist in ECR, and Terraform can't build/push one itself):
   ```bash
   make tf-init
   terraform -chdir=infra apply \
     -target=aws_ecr_repository.main -target=aws_ecr_repository.worker
   docker build backend/ -t <ecr_repo_url>:bootstrap
   docker push <ecr_repo_url>:bootstrap
   docker build -f backend/Dockerfile.worker backend/ -t <ecr_worker_repo_url>:bootstrap
   docker push <ecr_worker_repo_url>:bootstrap
   ```
5. **First full apply:**
   ```bash
   TF_VAR_database_url="$DATABASE_URL" TF_VAR_budget_email="you@example.com" \
     terraform -chdir=infra apply -var="image_tag=bootstrap"
   ```
   Creates everything else: the Cognito prod pool, S3 + CloudFront, SQS +
   DLQ, API Gateway, all three Lambdas, the EventBridge schedule, the SSM
   parameter and the budget alarm.
6. **Run the first migration by hand:**
   ```bash
   cd backend && ALEMBIC_DATABASE_URL="$ALEMBIC_DATABASE_URL" python -m alembic upgrade head
   ```
   `ALEMBIC_DATABASE_URL` is the only variable this needs: Alembic reads the
   DB-only `get_migration_settings()`, not the full app `Settings`.
7. **Verify:** `curl $(terraform -chdir=infra output -raw api_invoke_url)/health/deep`
   — all four checks green, against real Neon/S3/SQS/Cognito.
8. From here on, every push to `main` runs the pipeline. None of the above
   repeats.

### Upgrading an existing deployment to step 6a — one-time, by hand

Step 6a added the second ECR repo, `tricklens-worker`. `deploy.yml` pushes
the worker image *before* `terraform apply` runs, so on the first push that
included 6a the repo had to exist already. It was created once, locally:

```bash
make tf-init
TF_VAR_database_url="$DATABASE_URL" TF_VAR_budget_email="you@example.com" \
  terraform -chdir=infra apply \
    -target=aws_ecr_repository.worker -target=aws_ecr_lifecycle_policy.worker
```

Done for this deployment; a fresh account gets both repos in step 4 above.

## Fixing the CI roles

A fix to a CI role's own trust policy or permissions can't go through CI,
because CI can't assume the broken role. Apply it locally:

```bash
terraform -chdir=infra apply \
  -target=aws_iam_role.gha_deploy -target=aws_iam_role.gha_plan \
  -target=aws_iam_role_policy.gha_deploy -target=aws_iam_role_policy.gha_plan
```

and commit the change, so the next CI apply agrees with it.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `configure-aws-credentials`: "Not authorized to perform sts:AssumeRoleWithWebIdentity" | OIDC `sub` mismatch. Compare `var.github_oidc_sub_prefix` with the repo's `sub_claim_prefix` (step 3). Fix locally (above). |
| `terraform apply` in CI: "Error acquiring the state lock" or `AccessDenied` | The CI role lacks a permission (DynamoDB on the lock table, or a read the AWS provider makes). Fix in `infra/iam.tf`, apply locally (above). |
| Terraform reports `AWS_REGION` as a reserved Lambda environment variable | Lambda injects it. Don't add it to the Terraform-managed environment. |
| Lambda rejects the ECR image manifest | Build with `docker buildx build --platform linux/amd64 --provenance=false`; Lambda doesn't accept an OCI image index. |
| Lambda rejects reserved concurrency below the account minimum | AWS keeps 10 executions unreserved; remove the reservation or raise the account quota. |
| The API URL returns `Internal Server Error` while direct Lambda invocation works | Recreate `aws_lambda_permission.api_gateway`: replacing a Lambda removes its invoke policy. |
| Smoke test: "schema at revision X, code expects Y" | The `migrate` job didn't migrate. Check its log for real `Running upgrade` lines. |
| `migrate` is green but nothing migrated | Its retry loop must end on a command that can fail (see [infrastructure](components/infrastructure.md#migrations-run-before-the-new-image-goes-live-never-after)). |
| No `INFO` lines in CloudWatch (only `START`/`END`/`REPORT`) | An entrypoint isn't calling `configure_logging()` at import (see [services](components/services.md#logging-logspy)). |
| Clip stays `queued` in prod | Look for `Runtime.ImportModuleError` / `INIT` errors in the worker's logs; check the SQS event-source mapping is enabled. |
| `AccessDenied` on S3 in the worker's logs | The worker role's per-prefix S3 permissions (`raw/` read, `processed/` + `thumbs/` write). |
| Video or thumbnail URL returns 403 | CloudFront's Origin Access Control can't read the object. Check the bucket policy. |
