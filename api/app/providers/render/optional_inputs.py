"""Template-configured optional image connections for ComfyUI workflows."""

from copy import deepcopy

from app.services.workflow_service import WorkflowValidationError


def configure_optional_images(
    workflow: dict[str, object],
    metadata: dict[str, object],
    overrides: dict[str, object],
) -> None:
    controls = overrides.get("workflow_controls", {})
    if not isinstance(controls, dict):
        raise WorkflowValidationError("Workflow controls must be an object")
    references = metadata.get("optional_image_references", [])
    if not isinstance(references, list):
        raise WorkflowValidationError("Optional image configuration must be a list")
    for reference in references:
        if not isinstance(reference, dict):
            raise WorkflowValidationError("Invalid optional image configuration")
        key = str(reference.get("key", ""))
        target = workflow.get(str(reference.get("node_id", "")))
        input_name = str(reference.get("input_name", ""))
        source_id = str(reference.get("source_node_id", ""))
        source = workflow.get(source_id)
        if (
            not isinstance(target, dict)
            or not isinstance(target.get("inputs"), dict)
            or not isinstance(source, dict)
            or source.get("class_type") != "LoadImage"
            or not isinstance(source.get("inputs"), dict)
            or not key
            or not input_name
        ):
            raise WorkflowValidationError(
                "Optional image references a missing node/input"
            )
        enabled = controls.get(key, reference.get("enabled", False))
        if not isinstance(enabled, bool):
            raise WorkflowValidationError("Optional image enabled must be a boolean")
        inputs = target["inputs"]
        if enabled:
            asset_key = controls.get(key + "_asset", reference.get("asset_key"))
            if not isinstance(asset_key, str) or not asset_key.startswith(
                "workflow-media/"
            ):
                raise WorkflowValidationError(
                    "Upload a second source image before enabling it"
                )
            inputs[input_name] = [source_id, 0]
            source_meta = source.get("_meta", {})
            source["_meta"] = {
                **(deepcopy(source_meta) if isinstance(source_meta, dict) else {}),
                "ugc_reference_asset": asset_key,
                "title": str(reference.get("label", "Second image reference")),
            }
        else:
            inputs.pop(input_name, None)
            # Keep other uses of this loader intact, if there are any.
            used = any(
                isinstance(node, dict)
                and isinstance(node.get("inputs"), dict)
                and any(
                    isinstance(value, list) and value[:1] == [source_id]
                    for value in node["inputs"].values()
                )
                for node in workflow.values()
            )
            if not used:
                workflow.pop(source_id, None)
