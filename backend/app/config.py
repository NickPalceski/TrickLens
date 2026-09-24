"""Single source of truth for configuration.

Nothing outside this module reads os.environ, with one narrow exception:
app.services.secrets.resolve_database_url() (step 5) reads
DATABASE_URL_SSM_PARAM and writes DATABASE_URL into os.environ, because in
production DATABASE_URL lives in SSM Parameter Store as a SecureString, not
a plain Lambda env var (see docs/ARCHITECTURE.md's Decisions) — it has to
run *before* Settings() below can be constructed at all, so it can't go
through Settings the normal way. Everywhere else, this module is still the
only thing that reads an env var.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.secrets import resolve_database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    env: str = "dev"

    # --- Database ---
    database_url: str
    alembic_database_url: str = ""

    # --- AWS ---
    # Empty in production, which makes boto3 use real AWS endpoints.
    aws_endpoint_url: str = ""
    aws_region: str = "us-east-1"

    s3_bucket: str
    sqs_analysis_queue_url: str
    cdn_base_url: str

    # Presigned URLs are signed against boto_endpoint (LocalStack's
    # Docker-network hostname) — that's what the API container needs to
    # reach LocalStack, but it's also unreachable from anything outside the
    # compose network (a browser, Postman, curl on the host). Empty in
    # production, where boto_endpoint is already the real, externally
    # reachable S3 endpoint and there's nothing to rewrite.
    aws_public_endpoint_url: str = ""

    # --- API ---
    cors_origins: str = "http://localhost:3000"

    # --- Cognito ---
    # Unlike S3/SQS, this is *always* real Cognito, dev included — LocalStack
    # only emulates Cognito on a paid plan, and its JWKS support has known
    # bugs (hardcoded `kid`). Cognito's free tier (50k MAU) makes emulating it
    # pointless anyway. Dev and prod are simply two different pools, both set
    # here explicitly — there is no endpoint-override seam for this one.
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def boto_endpoint(self) -> str | None:
        """boto3 wants None (not "") to mean 'use the real AWS endpoint'."""
        return self.aws_endpoint_url or None

    @property
    def cognito_issuer(self) -> str:
        return f"https://cognito-idp.{self.aws_region}.amazonaws.com/{self.cognito_user_pool_id}"


class MigrationSettings(BaseSettings):
    """The database-only subset of Settings that Alembic needs.

    CI's migrate job (.github/workflows/deploy.yml) runs `alembic upgrade
    head` straight from the runner with only ALEMBIC_DATABASE_URL set. It has
    no S3 bucket, queue URL or CDN, and shouldn't need them. Building the
    full Settings there fails validation on those required fields.
    """

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    database_url: str = ""
    alembic_database_url: str = ""

    @property
    def sync_url(self) -> str:
        """psycopg URL for Alembic: ALEMBIC_DATABASE_URL, else DATABASE_URL re-driven."""
        url = self.alembic_database_url or self.database_url.replace("+asyncpg", "+psycopg")
        if not url:
            raise RuntimeError("Set ALEMBIC_DATABASE_URL or DATABASE_URL to run migrations.")
        return url


def get_migration_settings() -> MigrationSettings:
    resolve_database_url()
    return MigrationSettings()


@lru_cache
def get_settings() -> Settings:
    """Cached so Lambda parses the environment once per container, not per request.

    resolve_database_url() runs first so DATABASE_URL is in os.environ before
    Settings() reads it — see its docstring for why this is the one thing
    that reaches AWS before Settings exists to read AWS_ENDPOINT_URL etc.
    """
    resolve_database_url()
    return Settings()
