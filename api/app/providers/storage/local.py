import os
from pathlib import Path


class StorageError(RuntimeError):
    """Raised when a media object cannot be stored safely."""


class LocalStorageProvider:
    """Durable local object storage for development and single-node deployments."""

    def __init__(self, root: str | None = None) -> None:
        root_path = (
            root or os.getenv("MEDIA_STORAGE_ROOT") or "/var/lib/ugc-creator/media"
        )
        self.root = Path(root_path)

    def put(self, key: str, content: bytes) -> str:
        object_path = (self.root / key).resolve()
        root = self.root.resolve()
        if object_path != root and root not in object_path.parents:
            raise StorageError("Storage object key escapes the configured media root")
        object_path.parent.mkdir(parents=True, exist_ok=True)
        object_path.write_bytes(content)
        return key

    def get(self, key: str) -> bytes:
        object_path = (self.root / key).resolve()
        root = self.root.resolve()
        if object_path != root and root not in object_path.parents:
            raise StorageError("Storage object key escapes the configured media root")
        try:
            return object_path.read_bytes()
        except OSError as exc:
            raise StorageError("Stored media is unavailable") from exc
