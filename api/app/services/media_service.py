import json
import subprocess
import tempfile
from pathlib import Path


class MediaProcessingError(RuntimeError):
    """Raised when media metadata cannot be measured safely."""


def probe_audio_duration(audio: bytes, filename: str) -> float:
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix) as temporary_audio:
        temporary_audio.write(audio)
        temporary_audio.flush()
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    temporary_audio.name,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            raise MediaProcessingError("Audio duration could not be measured.") from exc

    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaProcessingError("Audio duration could not be measured.") from exc
    if duration <= 0:
        raise MediaProcessingError("Audio duration must be greater than zero.")
    return duration
