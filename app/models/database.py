from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, create_engine
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def create_engine_for_url(database_url: str):
    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL 必须使用 postgresql+psycopg:// 连接 PostgreSQL")
    return create_engine(database_url, pool_pre_ping=True)


def initialize_database(database_url: str) -> None:
    engine = create_engine_for_url(database_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
