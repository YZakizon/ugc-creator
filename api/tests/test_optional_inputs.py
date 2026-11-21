from copy import deepcopy
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.providers.render.comfyui_controls import apply_explicit_media_loader_overrides
from app.providers.render.optional_inputs import configure_optional_images
from app.services.workflow_service import WorkflowValidationError
from app.workers.render_tasks import apply_reference_image_media


def fixture() -> tuple[dict[str, object], dict[str, object]]:
    return (
        {
            "source": {"class_type": "LoadImage", "inputs": {"image": "first.png"}},
            "secondary": {"class_type": "LoadImage", "inputs": {"image": "second.png"}},
            "generator": {
                "class_type": "ExampleRenderer",
                "inputs": {"ref0": ["source", 0], "ref1": ["secondary", 0]},
            },
        },
        {
            "optional_image_references": [
                {
                    "key": "second_image",
                    "node_id": "generator",
                    "input_name": "ref1",
                    "source_node_id": "secondary",
                    "asset_key": "workflow-media/second.png",
                    "enabled": False,
                }
            ]
        },
    )


def test_disabled_reference_omitted_without_mutating_template() -> None:
    template, metadata = fixture()
    workflow = deepcopy(template)
    configure_optional_images(workflow, metadata, {})
    assert "secondary" not in workflow
    assert workflow["generator"]["inputs"] == {"ref0": ["source", 0]}
    assert "ref1" in template["generator"]["inputs"]


def test_enabled_reference_keeps_separate_durable_asset() -> None:
    workflow, metadata = fixture()
    configure_optional_images(
        workflow,
        metadata,
        {
            "workflow_controls": {
                "second_image": True,
                "second_image_asset": "workflow-media/custom.png",
            }
        },
    )
    assert workflow["generator"]["inputs"]["ref1"] == ["secondary", 0]
    assert (
        workflow["secondary"]["_meta"]["ugc_reference_asset"]
        == "workflow-media/custom.png"
    )


def test_invalid_optional_image_type_rejected() -> None:
    workflow, metadata = fixture()
    with pytest.raises(WorkflowValidationError, match="boolean"):
        configure_optional_images(
            workflow, metadata, {"workflow_controls": {"second_image": "false"}}
        )


def test_missing_optional_image_node_rejected() -> None:
    workflow, metadata = fixture()
    del workflow["secondary"]
    with pytest.raises(WorkflowValidationError, match="missing"):
        configure_optional_images(workflow, metadata, {})


@pytest.mark.asyncio
async def test_secondary_image_not_replaced_by_primary_override() -> None:
    workflow, metadata = fixture()
    configure_optional_images(
        workflow, metadata, {"workflow_controls": {"second_image": True}}
    )
    apply_explicit_media_loader_overrides(workflow, {"source_image": "new-primary.png"})
    renderer = Mock(upload=AsyncMock(return_value="new-secondary.png"))
    storage = Mock(get=Mock(return_value=b"second-image"))
    await apply_reference_image_media(workflow, renderer, storage, uuid4())
    assert workflow["source"]["inputs"]["image"] == "new-primary.png"
    assert workflow["secondary"]["inputs"]["image"] == "new-secondary.png"
    storage.get.assert_called_once_with("workflow-media/second.png")
