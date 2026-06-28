"""MySQL engine and transaction/session helpers."""

from __future__ import annotations

import re
from collections.abc import Generator
from contextlib import contextmanager
from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from novel_harness.config import Settings

from .orm import Base


def database_url_from_env(*, database: str | None = None, root: bool = False) -> str:
    """Construct a SQLAlchemy URL without exposing credentials in logs."""

    settings = Settings()
    host = settings.database_host
    port = settings.database_port
    name = database or settings.database_name
    user = quote_plus(settings.database_root_user if root else settings.database_user)
    password = quote_plus(settings.database_root_password if root else settings.database_password)
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


def create_mysql_engine(
    url: str | None = None,
    *,
    echo: bool = False,
    pool_pre_ping: bool = True,
) -> Engine:
    return create_engine(
        url or database_url_from_env(),
        echo=echo,
        pool_pre_ping=pool_pre_ping,
        pool_recycle=1800,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Commit a unit of work or roll it back on failure."""

    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database(engine: Engine) -> bool:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def create_schema_for_testing(engine: Engine) -> None:
    """Create tables for disposable tests; production uses Alembic."""

    Base.metadata.create_all(engine)


def provision_mysql() -> None:
    """Create the application database/user using configured root credentials.

    This is an explicit installation operation. Normal application startup must
    use the restricted application account and must not call this function.
    """

    settings = Settings()
    database = settings.database_name
    app_user = settings.database_user
    app_password = settings.database_password
    if not re.fullmatch(r"[A-Za-z0-9_]+", database):
        raise ValueError("DATABASE_NAME may contain only letters, digits, and '_'")
    if not re.fullmatch(r"[A-Za-z0-9_]+", app_user):
        raise ValueError("DATABASE_USER may contain only letters, digits, and '_'")
    escaped_password = app_password.replace("\\", "\\\\").replace("'", "\\'")
    root_url = database_url_from_env(database="mysql", root=True)
    engine = create_engine(root_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
            connection.execute(
                text(
                    f"CREATE USER IF NOT EXISTS '{app_user}'@'%' IDENTIFIED BY '{escaped_password}'"
                )
            )
            connection.execute(text(f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{app_user}'@'%'"))
    finally:
        engine.dispose()
