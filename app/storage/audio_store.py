from __future__ import annotations

import uuid
from pathlib import Path


class AudioStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_bytes(self, payload: bytes, suffix: str = ".wav") -> str:
        filename = f"{uuid.uuid4().hex}{suffix}"
        (self.base_dir / filename).write_bytes(payload)
        return filename

    def resolve_path(self, filename: str) -> Path:
        path = (self.base_dir / filename).resolve()
        if path.parent != self.base_dir.resolve():
            raise ValueError("Invalid filename")
        return path

