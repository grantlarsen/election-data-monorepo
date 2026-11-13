
from logging.config import fileConfig

from alembic import context

from app.database import Base, DATABASE_URL, engine
import app.models  # Existing model imports; preserved for backward compatibility
import app.models.core  # Ensure core tables are available to Alembic
import app.models.ingestion  # Register Step 5 provenance and observation tables


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # PostGIS manages this table itself.
    # Alembic must not attempt to drop it.
    if type_ == "table":
        return (
            parent_names["schema_qualified_table_name"]
            in target_metadata.tables
        )
    return True


def run_migrations_offline():
    context.configure(
        url=DATABASE_URL.render_as_string(
            hide_password=False
        ),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_name=include_name,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
