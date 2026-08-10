import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

SUPPORTED_VALUE_TYPES = frozenset(
    {"string", "template", "integer", "number", "boolean"}
)
ALLOWED_PLACEHOLDERS = frozenset(
    {
        "SCRIPT",
        "TOPIC",
        "HOOK",
        "VIDEO_PROMPT",
        "DURATION",
        "CHARACTER_NAME",
        "SOURCE_IMAGE",
        "AUDIO",
        "AUDIO_DURATION",
    }
)
PLACEHOLDER_PATTERN = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
TEMPLATE_TOKEN_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
AUDIO_DURATION_EXPRESSION_PATTERN = re.compile(
    r"\{\{\s*AUDIO_DURATION(?:\s*([+-])\s*(\d+(?:\.\d+)?))?\s*\}\}"
)
SEMANTIC_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


class WorkflowValidationError(ValueError):
    """Raised when a ComfyUI workflow or binding cannot be used safely."""


def workflow_checksum(workflow: Mapping[str, object]) -> str:
    canonical = json.dumps(workflow, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def workflow_uses_audio_duration(value: object) -> bool:
    if isinstance(value, str):
        return AUDIO_DURATION_EXPRESSION_PATTERN.search(value) is not None
    if isinstance(value, Mapping):
        return any(workflow_uses_audio_duration(item) for item in value.values())
    if isinstance(value, list):
        return any(workflow_uses_audio_duration(item) for item in value)
    return False


def validate_workflow(workflow: Mapping[str, object]) -> None:
    if not workflow:
        raise WorkflowValidationError("Workflow must contain at least one node")

    for node_id, raw_node in workflow.items():
        if not isinstance(node_id, str) or not node_id:
            raise WorkflowValidationError("Workflow node IDs must be non-empty strings")
        if not isinstance(raw_node, dict):
            raise WorkflowValidationError(f"Workflow node {node_id} must be an object")
        if not isinstance(raw_node.get("class_type"), str):
            raise WorkflowValidationError(
                f"Workflow node {node_id} is missing class_type"
            )
        inputs = raw_node.get("inputs")
        if not isinstance(inputs, dict):
            raise WorkflowValidationError(
                f"Workflow node {node_id} is missing an inputs object"
            )
        _validate_placeholders(raw_node)


def validate_bindings(
    workflow: Mapping[str, object], bindings: Sequence[Mapping[str, object]]
) -> None:
    validate_workflow(workflow)
    seen_keys: set[str] = set()
    for binding in bindings:
        semantic_key = _required_string(binding, "semantic_key")
        node_id = _required_string(binding, "node_id")
        input_name = _required_string(binding, "input_name")
        value_type = _required_string(binding, "value_type")
        if not SEMANTIC_KEY_PATTERN.fullmatch(semantic_key):
            raise WorkflowValidationError(
                f"Invalid workflow semantic key: {semantic_key}"
            )
        if value_type not in SUPPORTED_VALUE_TYPES:
            raise WorkflowValidationError(
                f"Unsupported workflow value type: {value_type}"
            )
        if semantic_key in seen_keys:
            raise WorkflowValidationError(
                f"Duplicate binding for semantic key: {semantic_key}"
            )
        seen_keys.add(semantic_key)
        raw_node = workflow.get(node_id)
        if not isinstance(raw_node, dict):
            raise WorkflowValidationError(
                f"Binding {semantic_key} references missing node {node_id}"
            )
        inputs = raw_node.get("inputs")
        if not isinstance(inputs, dict) or input_name not in inputs:
            raise WorkflowValidationError(
                f"Binding {semantic_key} references missing input "
                f"{node_id}.{input_name}"
            )


def prepare_workflow(
    workflow: Mapping[str, object],
    bindings: Sequence[Mapping[str, object]],
    values: Mapping[str, object],
) -> dict[str, object]:
    """Return an independent ComfyUI workflow copy with semantic values applied."""

    validate_bindings(workflow, bindings)
    prepared = copy.deepcopy(dict(workflow))
    for binding in bindings:
        semantic_key = _required_string(binding, "semantic_key")
        if semantic_key not in values:
            if bool(binding.get("required", True)):
                raise WorkflowValidationError(
                    f"Missing required workflow value: {semantic_key}"
                )
            continue
        node_id = _required_string(binding, "node_id")
        input_name = _required_string(binding, "input_name")
        value_type = _required_string(binding, "value_type")
        value = _coerce_value(semantic_key, values[semantic_key], value_type)
        node = prepared[node_id]
        if not isinstance(node, dict):  # validated above; keeps type narrowing local
            raise WorkflowValidationError(f"Workflow node {node_id} must be an object")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise WorkflowValidationError(f"Workflow node {node_id} has no inputs")
        inputs[input_name] = value

    _render_placeholders(prepared, values)
    return prepared


def _required_string(binding: Mapping[str, object], key: str) -> str:
    value = binding.get(key)
    if not isinstance(value, str) or not value:
        raise WorkflowValidationError(f"Binding field {key} must be a non-empty string")
    return value


def _coerce_value(semantic_key: str, value: object, value_type: str) -> object:
    if value_type in {"string", "template"}:
        if not isinstance(value, str):
            raise WorkflowValidationError(
                f"Workflow value {semantic_key} must be a string"
            )
        return value
    if value_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise WorkflowValidationError(
                f"Workflow value {semantic_key} must be an integer"
            )
        return value
    if value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WorkflowValidationError(
                f"Workflow value {semantic_key} must be a number"
            )
        return value
    if value_type == "boolean":
        if not isinstance(value, bool):
            raise WorkflowValidationError(
                f"Workflow value {semantic_key} must be a boolean"
            )
        return value
    raise WorkflowValidationError(f"Unsupported workflow value type: {value_type}")


def _validate_placeholders(value: object) -> None:
    if isinstance(value, str):
        for raw_token in TEMPLATE_TOKEN_PATTERN.findall(value):
            placeholder = raw_token.strip()
            if (
                placeholder not in ALLOWED_PLACEHOLDERS
                and AUDIO_DURATION_EXPRESSION_PATTERN.fullmatch("{{" + raw_token + "}}")
                is None
            ):
                raise WorkflowValidationError(
                    f"Unknown workflow placeholder: {{{{{raw_token}}}}}"
                )
    elif isinstance(value, dict):
        for item in value.values():
            _validate_placeholders(item)
    elif isinstance(value, list):
        for item in value:
            _validate_placeholders(item)


def _render_placeholders(value: Any, values: Mapping[str, object]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                value[key] = _render_string(item, values)
            else:
                _render_placeholders(item, values)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str):
                value[index] = _render_string(item, values)
            else:
                _render_placeholders(item, values)


def _render_string(value: str, values: Mapping[str, object]) -> object:
    def replace_duration(match: re.Match[str]) -> str:
        raw_duration = values.get("audio_duration")
        if isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
            raise WorkflowValidationError(
                "Missing workflow placeholder value: AUDIO_DURATION"
            )
        operator, raw_offset = match.groups()
        result = float(raw_duration)
        if operator and raw_offset:
            offset = float(raw_offset)
            result = result + offset if operator == "+" else result - offset
        if result <= 0:
            raise WorkflowValidationError("AUDIO_DURATION expression must be positive")
        return str(int(result)) if result.is_integer() else str(result)

    rendered = AUDIO_DURATION_EXPRESSION_PATTERN.sub(replace_duration, value)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        replacement = values.get(key.lower())
        if replacement is None:
            raise WorkflowValidationError(f"Missing workflow placeholder value: {key}")
        return str(replacement)

    rendered = PLACEHOLDER_PATTERN.sub(replace, rendered)
    if AUDIO_DURATION_EXPRESSION_PATTERN.fullmatch(value):
        numeric = float(rendered)
        return int(numeric) if numeric.is_integer() else numeric
    return rendered
