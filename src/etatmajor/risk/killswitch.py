"""Kill switch : arret d'urgence persistant.

Un arret d'urgence doit survivre a un redemarrage : un etat en memoire
reviendrait a la vie apres un crash, ce qui annulerait la protection.

Le fichier d'etat est un JSON minimaliste, ecrit de facon atomique (fichier
temporaire puis remplacement). L'engagement est irreversible sans un
rearmement explicite, trace et horodate.

Politique de panne (fail-closed)
--------------------------------
Toute situation ou l'etat de securite ne peut pas etre etabli avec certitude
engage le kill switch :

* fichier absent alors qu'il est declare obligatoire (``required=True``) ;
* fichier illisible (droits, disque, chemin invalide) ;
* JSON invalide ou schema inattendu (type incorrect, champs incoherents) ;
* echec d'ecriture de l'etat.

Un echec d'ecriture leve ``ConfigurationError`` apres avoir engage l'etat en
memoire : le processus appelant doit s'arreter, car la persistance n'est plus
garantie. Le rearmement est une action humaine explicite ; il est horodate et
conserve son motif dans le fichier d'etat.

Limites connues : le fichier n'est pas verrouille entre processus. Deux
processus qui ecrivent le meme fichier peuvent se contredire ; l'exploitation
doit garantir un seul ecrivain.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..core.errors import ConfigurationError


@dataclass
class KillSwitchState:
    """Etat persistant du kill switch."""

    engaged: bool = False
    reason: str = ""
    engaged_ts_ns: int = 0
    engagement_count: int = 0
    state_error: bool = False
    last_reset_ts_ns: int = 0
    last_reset_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class KillSwitch:
    """Arret d'urgence persistant, verrouille par defaut."""

    def __init__(self, path: str | Path | None = None, required: bool = False) -> None:
        self.path = Path(path) if path is not None else None
        self.required = required
        self.state = self._load()

    # -- chargement -----------------------------------------------------
    def _load(self) -> KillSwitchState:
        if self.path is None:
            if self.required:
                return self._fail_safe(
                    "kill switch is required but no persistent state path is configured"
                )
            return KillSwitchState()

        try:
            exists = self.path.exists()
        except OSError as exc:
            return self._fail_safe(
                f"kill switch state path cannot be inspected: {exc}"
            )

        if not exists:
            if self.required:
                return self._fail_safe(
                    f"kill switch state file is missing: {self.path}"
                )
            return KillSwitchState()

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError, ValueError) as exc:
            return self._fail_safe(
                f"kill switch state file unreadable: fail-safe engaged ({exc})"
            )

        try:
            return self._state_from_payload(payload)
        except (TypeError, ValueError, KeyError) as exc:
            return self._fail_safe(
                f"kill switch state file has an invalid schema: fail-safe engaged ({exc})"
            )

    _ALLOWED_KEYS = frozenset(
        {
            "engaged",
            "reason",
            "engaged_ts_ns",
            "engagement_count",
            "state_error",
            "last_reset_ts_ns",
            "last_reset_reason",
        }
    )

    @classmethod
    def _state_from_payload(cls, payload: Any) -> KillSwitchState:
        if not isinstance(payload, dict):
            raise ValueError("state must be a JSON object")

        unknown = set(payload) - cls._ALLOWED_KEYS
        if unknown:
            raise ValueError(f"unexpected keys: {sorted(unknown)}")
        if "engaged" not in payload:
            raise ValueError("engaged is required")

        engaged = payload["engaged"]
        if not isinstance(engaged, bool):
            raise ValueError("engaged must be a boolean")

        reason = payload.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("reason must be a string")

        engaged_ts_ns = payload.get("engaged_ts_ns", 0)
        if isinstance(engaged_ts_ns, bool) or not isinstance(engaged_ts_ns, int):
            raise ValueError("engaged_ts_ns must be an integer")
        if engaged_ts_ns < 0:
            raise ValueError("engaged_ts_ns must be >= 0")

        engagement_count = payload.get("engagement_count", 0)
        if isinstance(engagement_count, bool) or not isinstance(engagement_count, int):
            raise ValueError("engagement_count must be an integer")
        if engagement_count < 0:
            raise ValueError("engagement_count must be >= 0")

        state_error = payload.get("state_error", False)
        if not isinstance(state_error, bool):
            raise ValueError("state_error must be a boolean")

        last_reset_ts_ns = payload.get("last_reset_ts_ns", 0)
        if isinstance(last_reset_ts_ns, bool) or not isinstance(last_reset_ts_ns, int):
            raise ValueError("last_reset_ts_ns must be an integer")

        last_reset_reason = payload.get("last_reset_reason", "")
        if not isinstance(last_reset_reason, str):
            raise ValueError("last_reset_reason must be a string")

        return KillSwitchState(
            engaged=engaged,
            reason=reason,
            engaged_ts_ns=engaged_ts_ns,
            engagement_count=engagement_count,
            state_error=state_error,
            last_reset_ts_ns=last_reset_ts_ns,
            last_reset_reason=last_reset_reason,
        )

    def _fail_safe(self, message: str) -> KillSwitchState:
        return KillSwitchState(
            engaged=True,
            reason=message,
            engagement_count=1,
            state_error=True,
        )

    # -- persistance ----------------------------------------------------
    def _persist(self) -> None:
        if self.path is None:
            return
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(self.state.to_dict(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            # L'etat ne peut plus etre garanti sur disque : on engage en
            # memoire et on signale l'echec. L'appelant doit s'arreter.
            self.state = KillSwitchState(
                engaged=True,
                reason=(
                    f"kill switch state could not be persisted: {exc}; "
                    f"in-memory state engaged as a fail-safe"
                ),
                engagement_count=max(1, self.state.engagement_count),
                state_error=True,
                last_reset_ts_ns=self.state.last_reset_ts_ns,
                last_reset_reason=self.state.last_reset_reason,
            )
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ConfigurationError(
                f"kill switch state could not be persisted to {self.path}: {exc}"
            ) from exc

    # -- etat -----------------------------------------------------------
    @property
    def engaged(self) -> bool:
        return self.state.engaged

    @property
    def state_error(self) -> bool:
        """``True`` si l'etat a ete engage parce qu'il etait illisible."""
        return self.state.state_error

    def engage(self, reason: str, ts_ns: int = 0) -> KillSwitchState:
        """Engage l'arret d'urgence (irreversible sans rearmement explicite)."""
        if not self.state.engaged:
            self.state = KillSwitchState(
                engaged=True,
                reason=reason,
                engaged_ts_ns=ts_ns,
                engagement_count=self.state.engagement_count + 1,
                last_reset_ts_ns=self.state.last_reset_ts_ns,
                last_reset_reason=self.state.last_reset_reason,
            )
        self._persist()
        return self.state

    def reset(
        self, reason: str = "manual rearm", ts_ns: int = 0, operator: str = "human"
    ) -> KillSwitchState:
        """Rearme explicitement l'arret d'urgence (action humaine tracee).

        Le rearmement exige un fichier d'etat persistant et un motif non vide.
        L'horodatage et l'operateur sont conserves dans le fichier, ce qui
        permet de reconstituer l'historique de la decision.
        """
        if self.path is None:
            raise ConfigurationError(
                "kill switch reset requires a persistent state file"
            )
        if not str(reason).strip():
            raise ConfigurationError("kill switch reset requires a non-empty reason")
        self.state = KillSwitchState(
            engaged=False,
            reason=str(reason),
            engaged_ts_ns=0,
            engagement_count=self.state.engagement_count,
            state_error=False,
            last_reset_ts_ns=ts_ns,
            last_reset_reason=f"{reason} (operator: {operator})",
        )
        self._persist()
        return self.state

    def to_dict(self) -> dict:
        return {**self.state.to_dict(), "path": str(self.path) if self.path else None}
