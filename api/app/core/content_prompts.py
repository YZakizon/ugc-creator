import hashlib
import re

DEFAULT_CONTENT_PROMPT_TEMPLATE = (
    "You write conversational UGC scripts. Return content for Instagram and "
    "TikTok. Keep the speech natural and target about "
    "{{TARGET_DURATION_SECONDS}} seconds."
)
SUPPORTED_CONTENT_PROMPT_PLACEHOLDERS = ("TARGET_DURATION_SECONDS",)

_PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^{}]*?)\s*}}")


def validate_content_prompt_template(value: str) -> str:
    template = value.strip()
    if not template:
        raise ValueError("Content prompt template cannot be empty")

    unknown: set[str] = set()
    malformed = False

    def normalize_placeholder(match: re.Match[str]) -> str:
        nonlocal malformed
        name = match.group(1).strip()
        if not name:
            malformed = True
            return match.group(0)
        if name not in SUPPORTED_CONTENT_PROMPT_PLACEHOLDERS:
            unknown.add(name)
            return match.group(0)
        return f"{{{{{name}}}}}"

    normalized = _PLACEHOLDER_PATTERN.sub(normalize_placeholder, template)
    if unknown:
        raise ValueError(
            "Unsupported prompt placeholder: " + ", ".join(sorted(unknown))
        )
    placeholder_free = normalized
    for name in SUPPORTED_CONTENT_PROMPT_PLACEHOLDERS:
        placeholder_free = placeholder_free.replace(f"{{{{{name}}}}}", "")
    if malformed or "{" in placeholder_free or "}" in placeholder_free:
        raise ValueError("Malformed prompt placeholder")
    return normalized


def content_prompt_version(template: str) -> str:
    if template == DEFAULT_CONTENT_PROMPT_TEMPLATE:
        return "ugc-v1"
    digest = hashlib.sha256(template.encode("utf-8")).hexdigest()[:12]
    return f"custom-{digest}"
