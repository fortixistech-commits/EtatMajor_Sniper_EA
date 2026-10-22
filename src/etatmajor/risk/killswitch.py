"""Kill switch : arret d'urgence persistant.

Un arret d'urgence doit survivre a un redemarrage : un etat en memoire
reviendrait a la vie apres un crash, ce qui annulerait la protection.

Le fichier d'etat est un JSON minimaliste. L'engagement est irreversible
sans un rearmement explicite, trace et horodate.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..core.errors import ConfigurationError


@dataclass
class KillSwitchState:
    """Etat persistant du kill switch."""

    engaged: bool = False
    reason: str = ""
    engaged_ts_ns: int = 0
    engagement_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class KillSwitch:
    """Arret d'urgence persistant, verrouille par defaut."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.state = self._load()

    def _load(self) -> KillSwitchState:
        if self.path is None or not self.path.exists():
            return KillSwitchState()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Un fichier illisible est traite comme un kill switch engage :
            # l'echec de lecture ne doit jamais autoriser une operation.
            return KillSwitchState(
                engaged=True,
                reason="kill switch state file unreadable: fail-safe engaged",
                engagement_count=1,
            )
        return KillSwitchState(
            engaged=bool(payload.get("engaged", False)),
            reason=str(payload.get("reason", "")),
            engaged_ts_ns=int(payload.get("engaged_ts_ns", 0)),
            engagement_count=int(payload.get("engagement_count", 0)),
        )

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.state.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @property
    def engaged(self) -> bool:
        return self.state.engaged

    def engage(self, reason: str, ts_ns: int = 0) -> KillSwitchState:
        """Engage l'arret d'urgence (irreversible sans rearmement explicite)."""
        if not self.state.engaged:
            self.state = KillSwitchState(
                engaged=True,
                reason=reason,
                engaged_ts_ns=ts_ns,
                engagement_count=self.state.engagement_count + 1,
            )
            self._persist()
        return self.state

    def reset(self, reason: str = "manual rearm") -> KillSwitchState:
        """Rearme explicitement l'arret d'urgence (action humaine tracee)."""
        if self.path is None:
            raise ConfigurationError(
                "kill switch reset requires a persistent state file"
            )
        self.state = KillSwitchState(
            engaged=False,
            reason=reason,
            engaged_ts_ns=0,
            engagement_count=self.state.engagement_count,
        )
        self._persist()
        return self.state

    def to_dict(self) -> dict:
        return {**self.state.to_dict(), "path": str(self.path) if self.path else None}
