"""Kill switch : fichier sentinelle partagé entre processus. Seul un humain (CLI) peut le lever."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


class KillSwitch:
    def __init__(self, path: Path) -> None:
        self.path = path

    def is_active(self) -> bool:
        return self.path.exists()

    def info(self) -> dict[str, str] | None:
        if not self.is_active():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except (OSError, ValueError):
            return {"reason": "illisible", "at": ""}

    def activate(self, reason: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"reason": reason, "at": datetime.now(UTC).isoformat()}), encoding="utf-8"
        )

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
