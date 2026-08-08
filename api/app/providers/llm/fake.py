from app.providers.llm.contracts import (
    LLMProvider,
    UGCContentRequest,
    UGCContentResult,
)


class FakeLLMProvider(LLMProvider):
    """Deterministic provider for tests and local pipeline development."""

    async def generate_ugc_content(
        self, request: UGCContentRequest
    ) -> UGCContentResult:
        topic = request.topic.strip()
        content = {
            "speech_script": (
                f"Here is the thing about {topic}: it deserves a closer look. "
                "Save this for later and share it with someone who needs the reminder."
            ),
            "hook": f"The truth about {topic} is simpler than you think.",
            "instagram": {
                "title": topic,
                "description": f"A quick UGC take on {topic}.",
                "hashtags": ["#ugc", "#creator", "#tips"],
            },
            "tiktok": {
                "title": f"{topic} explained",
                "description": f"A conversational take on {topic}.",
                "hashtags": ["#tiktoktips", "#ugc", "#learn"],
            },
        }
        from app.providers.llm.contracts import UGCContent

        return UGCContentResult(
            content=UGCContent.model_validate(content),
            provider="fake",
            model="fake-ugc-v1",
            prompt_version="ugc-v1",
            request_id=None,
        )
