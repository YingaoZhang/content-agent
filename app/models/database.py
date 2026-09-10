from datetime import datetime, timezone

from sqlalchemy import DateTime, Engine, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "content_jobs"

    job_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(240))
    topic: Mapped[str] = mapped_column(String(120))
    objective: Mapped[str] = mapped_column(Text)
    theme: Mapped[str] = mapped_column(String(80))
    primary_audience: Mapped[str] = mapped_column(String(80))
    parent_job_id: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    request_json: Mapped[str] = mapped_column(Text)
    outline: Mapped[str] = mapped_column(Text, default="")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# Shared connection pools, keyed by URL. Creating and disposing an engine per
# operation defeats pooling, so callers reuse one engine for the process lifetime.
_engines: dict[str, Engine] = {}


def create_engine_for_url(database_url: str) -> Engine:
    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL 必须使用 postgresql+psycopg:// 连接 PostgreSQL")
    return create_engine(database_url, pool_pre_ping=True)


def get_engine(database_url: str) -> Engine:
    engine = _engines.get(database_url)
    if engine is None:
        engine = create_engine_for_url(database_url)
        _engines[database_url] = engine
    return engine


def ensure_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    # create_all() does not alter existing tables; backfill new columns idempotently.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE content_jobs ADD COLUMN IF NOT EXISTS error TEXT"))


def initialize_database(database_url: str) -> None:
    """Verify/create the schema once and keep the engine pooled for reuse."""
    ensure_schema(get_engine(database_url))


def dispose_engines() -> None:
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
