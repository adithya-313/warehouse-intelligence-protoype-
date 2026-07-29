from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# ---------------------------------------------------------------------------
# First, we need to tell our migration tool about the custom PostgreSQL
# "vector" data type that pgvector provides. Alembic works by comparing the
# real database schema against our SQLAlchemy model definitions. If we do
# NOT register the Vector type, Alembic will crash whenever it encounters
# a "vector" column during autogenerate because it doesn't know how to
# represent that type in Python.
#
# The fix: import the Vector class and register it into the PostgreSQL
# dialect's type map so Alembic can recognize, compare, and generate
# migration code for vector(768) columns.
# ---------------------------------------------------------------------------
# Import pgvector's custom "Vector" type so Alembic can detect and compare
# the vector(768) column on the ClinicalKnowledgeBase model during autogenerate.
# We also register it with the PostgreSQL dialect's internal type name map
# so Alembic knows how to represent "vector" columns in migration scripts.
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql.base import ischema_names
ischema_names["vector"] = Vector

# Import settings and metadata
from app.core.config import get_application_settings
from app.infrastructure.models import Base
# Ensure all db models are imported so Base metadata is populated
import app.infrastructure.db.models
import app.health_risk.infrastructure.db_models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    settings = get_application_settings()
    url = settings.database_url if settings.database_url else config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    settings = get_application_settings()
    configuration = config.get_section(config.config_ini_section, {})
    if settings.database_url:
        configuration["sqlalchemy.url"] = settings.database_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
