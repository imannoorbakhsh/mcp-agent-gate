"""Atomic JSON snapshots for durable, append-only agent runs."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .models import RunSnapshot


class SnapshotStore:
    """Persist one run state atomically without ever editing its history in place."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> RunSnapshot:
        return RunSnapshot.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, snapshot: RunSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = snapshot.model_dump_json(indent=2) + "\n"
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
