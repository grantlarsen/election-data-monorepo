
import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# Build the connection using Docker's environment variables.
DATABASE_URL = URL.create(
    "postgresql+psycopg",
    username=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    host=os.getenv("DB_HOST", "db"),
    port=int(os.getenv("DB_PORT", "5432")),
    database=os.environ["DB_NAME"],
)


# The engine manages connections to PostgreSQL.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


# Creates database sessions for queries and transactions.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


# All database models will inherit from this class.
class Base(DeclarativeBase):
    pass


# Dependency for FastAPI endpoints.
def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
