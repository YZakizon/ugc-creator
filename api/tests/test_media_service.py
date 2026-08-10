import subprocess
from types import SimpleNamespace

import pytest

from app.services.media_service import MediaProcessingError, probe_audio_duration


def test_probe_audio_duration_parses_ffprobe_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.media_service.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout='{"format":{"duration":"1.25"}}'
        ),
    )

    assert probe_audio_duration(b"audio", "speech.wav") == pytest.approx(1.25, abs=0.01)


def test_probe_audio_duration_rejects_invalid_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_media(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "ffprobe")

    monkeypatch.setattr("app.services.media_service.subprocess.run", reject_media)

    with pytest.raises(MediaProcessingError, match="could not be measured"):
        probe_audio_duration(b"not audio", "speech.mp3")
