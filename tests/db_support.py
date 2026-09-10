from sqlalchemy import delete
from sqlalchemy.orm import Session
from psycopg import connect

from app.models.database import JobRecord, create_engine_for_url, ensure_schema


TEST_DATABASE_URL = "postgresql+psycopg://content_agent:content_agent@127.0.0.1:5432/content_agent_test"


def reset_test_jobs() -> None:
    with connect(
        host="127.0.0.1",
        port=5432,
        dbname="content_agent",
        user="content_agent",
        password="content_agent",
        autocommit=True,
    ) as connection:
        database_exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            ("content_agent_test",),
        ).fetchone()
        if database_exists is None:
            connection.execute("CREATE DATABASE content_agent_test")

    engine = create_engine_for_url(TEST_DATABASE_URL)
    try:
        ensure_schema(engine)
        with Session(engine) as session:
            session.execute(delete(JobRecord))
            session.commit()
    finally:
        engine.dispose()
