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
    """Create isolated application/Auth/Billing databases and service users.

    This is an explicit installation operation. Normal application startup must
    use restricted service accounts and must not call this function.
    """

    settings = Settings()
    accounts = (
        (settings.database_name, settings.database_user, settings.database_password),
        (
            settings.auth_database_name,
            settings.auth_database_user or settings.database_user,
            settings.auth_database_password or settings.database_password,
        ),
        (
            settings.billing_database_name,
            settings.billing_database_user or settings.database_user,
            settings.billing_database_password or settings.database_password,
        ),
    )
    for database, user, _password in accounts:
        if not re.fullmatch(r"[A-Za-z0-9_]+", database):
            raise ValueError("database names may contain only letters, digits, and '_'")
        if not re.fullmatch(r"[A-Za-z0-9_]+", user):
            raise ValueError("database users may contain only letters, digits, and '_'")
    user_passwords: dict[str, str] = {}
    for _database, user, password in accounts:
        previous = user_passwords.setdefault(user, password)
        if previous != password:
            raise ValueError("the same database user cannot be configured with two passwords")
    root_url = database_url_from_env(database="mysql", root=True)
    engine = create_engine(root_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            for user, password in user_passwords.items():
                escaped_password = password.replace("\\", "\\\\").replace("'", "\\'")
                connection.execute(
                    text(
                        f"CREATE USER IF NOT EXISTS '{user}'@'%' IDENTIFIED BY '{escaped_password}'"
                    )
                )
            for database, user, _password in accounts:
                connection.execute(
                    text(
                        f"CREATE DATABASE IF NOT EXISTS `{database}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                )
                connection.execute(text(f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{user}'@'%'"))
    finally:
        engine.dispose()
