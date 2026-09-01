import re
from dataclasses import dataclass

from app.services.workflow_service import SEED_INPUT_PATTERN

type ScalarValue = str | int | float | bool


@dataclass(frozen=True)
class WorkflowField:
    node_id: str
    class_type: str
    title: str
    input_name: str
    value: ScalarValue


def rendered_ltx_controls(workflow: dict[str, object]) -> list[dict[str, object]]:
    """Extract compact LTX controls from a prepared ComfyUI workflow."""
    fields = _scalar_fields(workflow)
    controls = [
        ("Image source", _find(fields, "loadimage", "image")),
        ("Audio source", _find(fields, "loadaudio", "audio")),
        ("Prompt", _prompt_field(fields)),
        ("FPS", _numeric_field(fields, r"^frame rate$", "fps")),
        ("Duration", _numeric_field(fields, "duration", "duration")),
        ("Seed", _primary_seed_field(workflow, fields)),
        ("Width", _numeric_field(fields, r"^width$", "width")),
        ("Height", _numeric_field(fields, r"^height$", "height")),
    ]
    return [
        {
            "label": label,
            "node_id": field.node_id,
            "input_name": field.input_name,
            "value": field.value,
        }
        for label, field in controls
        if field is not None
    ]


def apply_explicit_media_loader_overrides(
    workflow: dict[str, object], values: dict[str, object]
) -> None:
    """Apply explicit render media to every matching ComfyUI loader node.

    Semantic bindings remain the primary mapping mechanism. This guard handles
    ComfyUI workflows with multiple LoadImage/LoadAudio nodes where the visible
    or imported binding points at one loader but the actual downstream graph
    reads from another. It only touches the per-render workflow copy.
    """

    media_inputs = {
        "loadimage": ("source_image", "image"),
        "loadaudio": ("audio", "audio"),
    }
    for raw_node in workflow.values():
        if not isinstance(raw_node, dict):
            continue
        class_type = raw_node.get("class_type")
        inputs = raw_node.get("inputs")
        if not isinstance(class_type, str) or not isinstance(inputs, dict):
            continue
        for class_pattern, (semantic_key, input_name) in media_inputs.items():
            value = values.get(semantic_key)
            if not isinstance(value, str) or not value:
                continue
            if re.search(class_pattern, class_type, re.IGNORECASE) and isinstance(
                inputs.get(input_name), str
            ):
                inputs[input_name] = value


def inferred_ltx_bindings(
    workflow: dict[str, object],
    existing_bindings: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return bindings for visible LTX controls that are not already bound.

    These bindings are inferred from the workflow structure at render-attempt
    snapshot time. The stored template JSON is not mutated, and existing user
    bindings always win.
    """

    existing_keys = {
        binding.get("semantic_key")
        for binding in existing_bindings
        if isinstance(binding.get("semantic_key"), str)
    }
    fields = _scalar_fields(workflow)
    controls: list[tuple[str, str, str, WorkflowField | None]] = [
        ("video_prompt", "template", "Prompt", _prompt_field(fields)),
        ("fps", "integer", "FPS", _numeric_field(fields, r"^frame rate$", "fps")),
        (
            "duration",
            "integer",
            "Duration",
            _numeric_field(fields, "duration", "duration"),
        ),
        ("seed", "integer", "Seed", _primary_seed_field(workflow, fields)),
    ]
    inferred: list[dict[str, object]] = []
    for semantic_key, value_type, _label, field in controls:
        if field is None or semantic_key in existing_keys:
            continue
        if value_type == "integer" and (
            not isinstance(field.value, int) or isinstance(field.value, bool)
        ):
            continue
        inferred.append(
            {
                "semantic_key": semantic_key,
                "node_id": field.node_id,
                "input_name": field.input_name,
                "value_type": value_type,
                "transform": {},
                "required": False,
            }
        )
        existing_keys.add(semantic_key)
    return inferred


def _scalar_fields(workflow: dict[str, object]) -> list[WorkflowField]:
    fields: list[WorkflowField] = []
    for node_id, raw_node in workflow.items():
        if not isinstance(raw_node, dict):
            continue
        class_type = raw_node.get("class_type")
        inputs = raw_node.get("inputs")
        if not isinstance(class_type, str) or not isinstance(inputs, dict):
            continue
        metadata = raw_node.get("_meta")
        title = (
            metadata.get("title", "")
            if isinstance(metadata, dict) and isinstance(metadata.get("title"), str)
            else ""
        )
        for input_name, value in inputs.items():
            if isinstance(input_name, str) and isinstance(
                value, (str, int, float, bool)
            ):
                fields.append(
                    WorkflowField(
                        node_id=node_id,
                        class_type=class_type,
                        title=title,
                        input_name=input_name,
                        value=value,
                    )
                )
    return fields


def _find(
    fields: list[WorkflowField], class_pattern: str, input_name: str
) -> WorkflowField | None:
    return next(
        (
            field
            for field in fields
            if re.search(class_pattern, field.class_type, re.IGNORECASE)
            and field.input_name.casefold() == input_name.casefold()
        ),
        None,
    )


def _prompt_field(fields: list[WorkflowField]) -> WorkflowField | None:
    return next(
        (
            field
            for field in fields
            if isinstance(field.value, str)
            and field.title.strip().casefold() == "prompt"
        ),
        None,
    ) or next(
        (
            field
            for field in fields
            if isinstance(field.value, str)
            and re.search("primitivestringmultiline", field.class_type, re.IGNORECASE)
        ),
        None,
    )


def _numeric_field(
    fields: list[WorkflowField], title_pattern: str, input_name: str
) -> WorkflowField | None:
    candidates = [
        field
        for field in fields
        if isinstance(field.value, (int, float)) and not isinstance(field.value, bool)
    ]
    return next(
        (
            field
            for field in candidates
            if re.search(title_pattern, field.title, re.IGNORECASE)
        ),
        None,
    ) or next(
        (
            field
            for field in candidates
            if field.input_name.casefold() == input_name.casefold()
        ),
        None,
    )


def _primary_seed_field(
    workflow: dict[str, object], fields: list[WorkflowField]
) -> WorkflowField | None:
    seeds = [
        field
        for field in fields
        if isinstance(field.value, int)
        and not isinstance(field.value, bool)
        and re.search("randomnoise", field.class_type, re.IGNORECASE)
        and SEED_INPUT_PATTERN.fullmatch(field.input_name)
    ]
    for seed in seeds:
        sampler = next(
            (
                node
                for node in workflow.values()
                if isinstance(node, dict)
                and re.search(
                    "samplercustomadvanced",
                    str(node.get("class_type", "")),
                    re.IGNORECASE,
                )
                and _linked_node(node.get("inputs"), "noise") == seed.node_id
            ),
            None,
        )
        if not isinstance(sampler, dict):
            continue
        sigmas_node_id = _linked_node(sampler.get("inputs"), "sigmas")
        sigmas_node = workflow.get(sigmas_node_id) if sigmas_node_id else None
        sigmas = (
            sigmas_node.get("inputs", {}).get("sigmas")
            if isinstance(sigmas_node, dict)
            and isinstance(sigmas_node.get("inputs"), dict)
            else None
        )
        if isinstance(sigmas, str) and re.match(r"^\s*1(?:\.0+)?(?:\s*,|\s*$)", sigmas):
            return seed
    return (
        seeds[-1]
        if seeds
        else next(
            (
                field
                for field in fields
                if isinstance(field.value, int)
                and not isinstance(field.value, bool)
                and SEED_INPUT_PATTERN.fullmatch(field.input_name)
            ),
            None,
        )
    )


def _linked_node(inputs: object, input_name: str) -> str | None:
    if not isinstance(inputs, dict):
        return None
    value = inputs.get(input_name)
    return (
        value[0]
        if isinstance(value, list) and value and isinstance(value[0], str)
        else None
    )
