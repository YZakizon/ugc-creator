import os
from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import models  # noqa: F401 - registers models with Base.metadata
from app.db.base import Base


def database_url() -> str | None:
    return os.getenv("DATABASE_URL")


def create_database_engine() -> Engine | None:
    url = database_url()
    if not url:
        return None
    return create_engine(url, pool_pre_ping=True)


def initialize_database(engine: Engine | None) -> None:
    if engine is not None:
        Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    with factory() as session:
        yield session
