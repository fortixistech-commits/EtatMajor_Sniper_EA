"""Identite de session et versions de configuration.

Une session identifie une execution de maniere **deterministe** : le meme
couple (configuration, donnees, instant de depart) redonne le meme
identifiant. Aucun alea n'est employe : la reproductibilite prime.

Les versions (configuration, strategie, dataset) sont portees par le rapport
et par le journal : un resultat doit toujours pouvoir etre rattache a ce
qui l'a produit.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SessionIdentity:
    """Identite d'une session de simulation."""

    session_id: str
    strategy_id: str
    strategy_version: str
    config_fingerprint: str
    dataset_fingerprint: str
    created_ts_ns: int
    code_version: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_session_identity(
    *,
    strategy_id: str,
    strategy_version: str,
    config_fingerprint: str,
    dataset_fingerprint: str,
    created_ts_ns: int,
    code_version: str = "unknown",
) -> SessionIdentity:
    """Construit une identite de session deterministe.

    L'identifiant est le SHA-256 tronque des entrees de la session : deux
    executions identiques produisent le meme identifiant, ce qui permet de
    comparer deux rapports sans ambiguite.
    """
    payload = "|".join(
        [
            strategy_id,
            strategy_version,
            config_fingerprint,
            dataset_fingerprint,
            str(created_ts_ns),
            code_version,
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return SessionIdentity(
        session_id=f"S-{digest}",
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        config_fingerprint=config_fingerprint,
        dataset_fingerprint=dataset_fingerprint,
        created_ts_ns=created_ts_ns,
        code_version=code_version,
    )
