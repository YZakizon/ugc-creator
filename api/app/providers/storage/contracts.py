from typing import Protocol


class StorageProvider(Protocol):
    def put(self, key: str, content: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...
