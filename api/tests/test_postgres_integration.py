"""Integration coverage for the repository against the dedicated test database.

Run with TEST_DATABASE_URL pointing at an isolated PostgreSQL database. The normal
unit suite remains dependency-free and uses SQLite/in-memory repositories.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import models  # noqa: F401
from app.db.base import Base
from app.repositories import (
    SqlAlchemyBatchRepository,
    SqlAlchemyConfigurationRepository,
)
from app.schemas import (
    BatchCreate,
    RenderProfileSetupCreate,
    VoiceProfileCreate,
)

database_url = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(not database_url, reason="TEST_DATABASE_URL is not configured")
def test_postgres_persists_profile_and_batch_relationships() -> None:
    assert database_url is not None
    engine = create_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    configuration = SqlAlchemyConfigurationRepository(factory)
    batches = SqlAlchemyBatchRepository(factory)

    voice = configuration.create_voice_profile(
        VoiceProfileCreate(
            name="Elena voice",
            provider="elevenlabs",
            provider_voice_id="voice-elena",
        )
    )
    profile = configuration.create_render_profile_setup(
        RenderProfileSetupCreate(
            profile_name="Elena Shelf",
            character_name="Elena",
            voice_profile_id=voice.id,
            renderer_provider="comfyui",
        )
    )
    batch = batches.create_batch(
        BatchCreate(
            name="Tuesday ideas",
            topics=["Burnout is not laziness", "A reminder for overthinkers"],
            default_render_profile_id=profile.id,
        )
    )

    with engine.connect() as connection:
        assert (
            connection.execute(text("select count(*) from batches")).scalar_one() == 1
        )
        assert (
            connection.execute(text("select count(*) from topic_jobs")).scalar_one()
            == 2
        )
    assert all(job.render_profile_id == profile.id for job in batch.jobs)
    engine.dispose()
