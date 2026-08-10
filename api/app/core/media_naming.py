import re
import unicodedata


def short_topic_name(topic: str, max_length: int = 48) -> str:
    normalized = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug[:max_length].rstrip("-") or "topic"


def generated_media_filename(
    topic: str,
    content_number: int,
    output_number: int,
    extension: str,
) -> str:
    safe_extension = re.sub(r"[^a-z0-9]", "", extension.lower()) or "bin"
    return (
        f"{short_topic_name(topic)}_content{content_number}_"
        f"{output_number:04d}.{safe_extension}"
    )
