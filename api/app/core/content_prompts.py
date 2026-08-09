import hashlib
import re

DEFAULT_CONTENT_PROMPT_TEMPLATE = (
    "You write conversational UGC scripts. Return content for Instagram and "
    "TikTok. Keep the speech natural and target about "
    "{{TARGET_DURATION_SECONDS}} seconds."
)
SUPPORTED_CONTENT_PROMPT_PLACEHOLDERS = ("TARGET_DURATION_SECONDS",)

_PLACEHOLDER_PATTERN = re.compile(r"{{\s*([A-Z][A-Z0-9_]*)\s*}}")


def validate_content_prompt_template(value: str) -> str:
    template = value.strip()
    if not template:
        raise ValueError("Content prompt template cannot be empty")
    unknown = sorted(
        set(_PLACEHOLDER_PATTERN.findall(template))
        - set(SUPPORTED_CONTENT_PROMPT_PLACEHOLDERS)
    )
    if unknown:
        raise ValueError("Unsupported prompt placeholder: " + ", ".join(unknown))
    return template


def content_prompt_version(template: str) -> str:
    if template == DEFAULT_CONTENT_PROMPT_TEMPLATE:
        return "ugc-v1"
    digest = hashlib.sha256(template.encode("utf-8")).hexdigest()[:12]
    return f"custom-{digest}"
