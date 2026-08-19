"""Single source of truth for configuration.

Nothing outside this module reads os.environ. That rule is what lets the same
image run locally against LocalStack and in Lambda against real AWS with no
code change — only environment differs.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    """Cached so Lambda parses the environment once per container, not per request."""
    return Settings()
