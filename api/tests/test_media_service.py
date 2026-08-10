import io
import wave

import pytest

from app.services.media_service import MediaProcessingError, probe_audio_duration


def wav_bytes(duration_seconds: float, sample_rate: int = 8_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * int(sample_rate * duration_seconds))
    return output.getvalue()


def test_probe_audio_duration_uses_real_media_duration() -> None:
    assert probe_audio_duration(wav_bytes(1.25), "speech.wav") == pytest.approx(
        1.25, abs=0.01
    )


def test_probe_audio_duration_rejects_invalid_audio() -> None:
    with pytest.raises(MediaProcessingError, match="could not be measured"):
        probe_audio_duration(b"not audio", "speech.mp3")
