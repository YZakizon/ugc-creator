"""MiniMax-specific ComfyUI parameters; core job fields stay generic."""

import math

from app.services.workflow_service import WorkflowValidationError

ASPECT_RATIOS = (
    "1:1 (Square)",
    "2:3 (Portrait Photo)",
    "3:2 (Photo)",
    "3:4 (Portrait Standard)",
    "4:3 (Standard)",
    "9:16 (Portrait Widescreen)",
    "16:9 (Widescreen)",
    "21:9 (Ultrawide)",
)


def configure_minimax_image_size(
    workflow: dict[str, object], overrides: dict[str, object]
) -> None:
    controls = overrides.get("workflow_controls", {})
    if not isinstance(controls, dict):
        return
    for node in list(workflow.values()):
        if (
            not isinstance(node, dict)
            or node.get("class_type") != "MiniMaxH3ReferenceToVideo"
        ):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        width, height = inputs.get("width"), inputs.get("height")
        if not (
            isinstance(width, list)
            and isinstance(height, list)
            and len(width) == 2
            and len(height) == 2
            and width[0] == height[0]
        ):
            continue
        selector = workflow.get(str(width[0]))
        if (
            not isinstance(selector, dict)
            or selector.get("class_type") != "ResolutionSelector"
        ):
            continue
        settings = selector.get("inputs")
        if not isinstance(settings, dict):
            continue
        megapixels = controls.get("image_megapixels", settings.get("megapixels"))
        aspect_ratio = controls.get("image_aspect_ratio", settings.get("aspect_ratio"))
        multiple = controls.get("image_multiple", settings.get("multiple"))
        if (
            isinstance(megapixels, bool)
            or not isinstance(megapixels, (int, float))
            or not math.isfinite(megapixels)
            or not 0.1 <= megapixels <= 16
        ):
            raise WorkflowValidationError("Image megapixels must be between 0.1 and 16")
        if aspect_ratio not in ASPECT_RATIOS:
            raise WorkflowValidationError("Choose a supported image aspect ratio")
        if (
            isinstance(multiple, bool)
            or not isinstance(multiple, int)
            or not 8 <= multiple <= 128
            or (multiple - 8) % 4
        ):
            raise WorkflowValidationError(
                "Image size multiple must be 8–128 in steps of 4"
            )
        settings.update(
            megapixels=megapixels, aspect_ratio=aspect_ratio, multiple=multiple
        )
