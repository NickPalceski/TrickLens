"""Alembic environment.

Runs synchronously (psycopg) while the application runs asynchronously
(asyncpg). Same database, two drivers — migrations are a short-lived
one-shot process and gain nothing from async.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_migration_settings

# Importing the package registers every model on Base.metadata. Without this,
# autogenerate sees an empty schema and cheerfully writes a migration that
# drops all your tables.
from app.models import Base  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Not get_settings(): that requires S3/SQS/CDN config a migration has no use
# for, and CI's migrate job only provides ALEMBIC_DATABASE_URL.
config.set_main_option("sqlalchemy.url", get_migration_settings().sync_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it (`alembic upgrade --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Catch column type changes, not just added/dropped columns.
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
