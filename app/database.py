import time

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url):
    options = dict(pool_pre_ping=True, pool_recycle=300, pool_size=3, max_overflow=2)
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, hide_parameters=True, **options)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session


def initialize_database():
    # Import registers all tables before create_all.
    from app import models  # noqa: F401
    for attempt in range(2):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            Base.metadata.create_all(engine)
            return
        except DBAPIError:
            if attempt:
                raise RuntimeError("Database startup failed; check connection settings") from None
            engine.dispose()
            time.sleep(1)


def begin_write(db):
    # Serialize SQLite writers; PostgreSQL locks the target row in the route.
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
