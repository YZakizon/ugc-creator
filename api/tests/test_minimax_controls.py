from copy import deepcopy

import pytest

from app.providers.render.minimax_controls import configure_minimax_image_size
from app.services.workflow_service import WorkflowValidationError


def template() -> dict[str, object]:
    return {
        "custom-size": {
            "class_type": "ResolutionSelector",
            "inputs": {
                "aspect_ratio": "9:16 (Portrait Widescreen)",
                "megapixels": 0.5,
                "multiple": 32,
            },
        },
        "custom-generator": {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": {"width": ["custom-size", 0], "height": ["custom-size", 1]},
        },
    }


def test_size_uses_template_defaults_and_dynamic_node_ids() -> None:
    original = template()
    workflow = deepcopy(original)
    configure_minimax_image_size(workflow, {})
    assert workflow == original
    configure_minimax_image_size(
        workflow,
        {
            "workflow_controls": {
                "image_megapixels": 1.25,
                "image_aspect_ratio": "16:9 (Widescreen)",
                "image_multiple": 64,
            }
        },
    )
    assert workflow["custom-size"]["inputs"]["megapixels"] == 1.25
    assert workflow["custom-size"]["inputs"]["multiple"] == 64
    assert original["custom-size"]["inputs"]["megapixels"] == 0.5


@pytest.mark.parametrize(
    "key,value",
    [
        ("image_megapixels", 0),
        ("image_megapixels", 17),
        ("image_megapixels", float("nan")),
        ("image_megapixels", True),
        ("image_megapixels", ""),
        ("image_multiple", 31),
        ("image_multiple", 4),
        ("image_aspect_ratio", "invalid"),
    ],
)
def test_invalid_size_values_rejected(key: str, value: object) -> None:
    with pytest.raises(WorkflowValidationError):
        configure_minimax_image_size(template(), {"workflow_controls": {key: value}})


def test_unrelated_workflow_untouched() -> None:
    workflow = template()
    workflow["custom-generator"]["class_type"] = "OtherRenderer"
    original = deepcopy(workflow)
    configure_minimax_image_size(
        workflow, {"workflow_controls": {"image_megapixels": 2}}
    )
    assert workflow == original


def test_queue_snapshots_size_and_optional_image_without_changing_template() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.models import (
        Batch,
        Character,
        MediaAsset,
        RenderProfile,
        TopicJob,
        WorkflowTemplate,
    )
    from app.render_repository import RenderExecutionRepository
    from app.schemas import RenderNodeCreate

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    original = template()
    original["primary"] = {"class_type": "LoadImage", "inputs": {"image": "first.png"}}
    original["secondary"] = {
        "class_type": "LoadImage",
        "inputs": {"image": "second.png"},
    }
    with factory() as session:
        character = Character(name="Example", slug="example")
        workflow = WorkflowTemplate(
            name="H3",
            renderer_provider="comfyui",
            workflow_json=original,
            checksum="test",
            metadata_json={
                "optional_image_references": [
                    {
                        "key": "second_image",
                        "node_id": "custom-generator",
                        "input_name": "ref_images.ref_image_1",
                        "source_node_id": "secondary",
                        "enabled": False,
                    }
                ]
            },
        )
        session.add_all([character, workflow])
        session.flush()
        profile = RenderProfile(
            name="H3",
            character=character,
            renderer_provider="comfyui",
            workflow_template_id=workflow.id,
        )
        session.add(profile)
        session.flush()
        job = TopicJob(
            batch=Batch(name="Video"),
            topic="Video",
            render_profile_id=profile.id,
            render_overrides={
                "workflow_controls": {
                    "image_megapixels": 1.25,
                    "second_image": True,
                    "second_image_asset": "workflow-media/new.png",
                }
            },
        )
        job.media_assets = [
            MediaAsset(
                kind="audio", object_key="test.mp3", filename="test.mp3", size_bytes=1
            )
        ]
        session.add(job)
        session.commit()
        job_id, template_id = job.id, workflow.id
    repo = RenderExecutionRepository(factory)
    node = repo.create_node(
        RenderNodeCreate(name="Local", base_url="http://comfyui:8188")
    )
    attempt = repo.queue_attempt(job_id, node.id)
    assert attempt.workflow_snapshot["custom-size"]["inputs"]["megapixels"] == 1.25
    assert attempt.workflow_snapshot["custom-generator"]["inputs"][
        "ref_images.ref_image_1"
    ] == ["secondary", 0]
    assert (
        attempt.workflow_snapshot["secondary"]["_meta"]["ugc_reference_asset"]
        == "workflow-media/new.png"
    )
    with factory() as session:
        assert session.get(WorkflowTemplate, template_id).workflow_json == original
