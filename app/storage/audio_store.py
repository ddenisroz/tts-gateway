from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path


class AudioStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_bytes(self, payload: bytes, suffix: str = ".wav") -> str:
        safe_suffix = suffix if str(suffix).startswith(".") else ".wav"
        filename = f"{uuid.uuid4().hex}{safe_suffix}"
        path = self.base_dir / filename
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=f"{filename}.", suffix=".tmp", dir=str(self.base_dir))
        try:
            with os.fdopen(tmp_fd, "wb") as handle:
                handle.write(payload)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        return filename

    def resolve_path(self, filename: str) -> Path:
        path = (self.base_dir / filename).resolve()
        if path.parent != self.base_dir.resolve():
            raise ValueError("Invalid filename")
        return path
