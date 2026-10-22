"""Profil de challenge : donnee versionnee, verifiee, datee.

Un profil incomplet ne peut pas servir a conclure. Les regles inconnues sont
declarees dans `ambiguous_rules` ; le moteur les evalue sous toutes leurs
interpretations et retient le verdict le plus defavorable.

Le format est TOML (bibliotheque standard) : le profil est donc lisible,
diffable et versionnable comme le reste de la configuration du projet.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..core.errors import ConfigurationError


class ProfileStatus(str, Enum):
    """Statut de verification d'un profil."""

    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    INVALID = "INVALID"

    @property
    def allows_conclusion(self) -> bool:
        """``True`` si le profil peut produire un verdict de conformite."""
        return self is ProfileStatus.VERIFIED


@dataclass(frozen=True)
class ChallengeStep:
    """Une etape du challenge (palier de validation)."""

    index: int
    profit_target_percent: float
    profit_target_amount: float
    min_profitable_days: int
    reference_capital: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "profit_target_percent": self.profit_target_percent,
            "profit_target_amount": self.profit_target_amount,
            "min_profitable_days": self.min_profitable_days,
            "reference_capital": self.reference_capital,
        }


@dataclass(frozen=True)
class ProfileLimits:
    """Limites de perte du programme."""

    max_daily_loss_percent: float
    max_daily_loss_amount: float
    max_total_loss_percent: float
    max_total_loss_amount: float
    drawdown_type: str = "UNRESOLVED"
    drawdown_basis: str = "UNRESOLVED"
    daily_reset_time: str = "UNRESOLVED"
    daily_reset_timezone: str = "UNRESOLVED"

    @property
    def daily_basis_is_resolved(self) -> bool:
        return self.drawdown_basis != "UNRESOLVED"

    @property
    def reset_time_is_resolved(self) -> bool:
        return self.daily_reset_time != "UNRESOLVED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_daily_loss_percent": self.max_daily_loss_percent,
            "max_daily_loss_amount": self.max_daily_loss_amount,
            "max_total_loss_percent": self.max_total_loss_percent,
            "max_total_loss_amount": self.max_total_loss_amount,
            "drawdown_type": self.drawdown_type,
            "drawdown_basis": self.drawdown_basis,
            "daily_reset_time": self.daily_reset_time,
            "daily_reset_timezone": self.daily_reset_timezone,
        }


@dataclass(frozen=True)
class AmbiguousRule:
    """Regle dont la lecture officielle n'est pas etablie."""

    id: str
    topic: str
    description: str
    status: str
    evaluation_policy: str
    interpretations: tuple[str, ...] = ()
    assumed: str = ""

    @property
    def is_resolved(self) -> bool:
        return self.status != "UNRESOLVED"

    @property
    def is_blocking(self) -> bool:
        return self.evaluation_policy == "blocking_for_real_evaluation"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "description": self.description,
            "status": self.status,
            "evaluation_policy": self.evaluation_policy,
            "interpretations": list(self.interpretations),
            "assumed": self.assumed,
        }


@dataclass(frozen=True)
class ChallengeProfile:
    """Profil complet d'un programme de prop firm."""

    profile_id: str
    profile_version: str
    profile_status: ProfileStatus
    verified_on: str
    verified_by: str
    sources: tuple[str, ...]
    program_name: str
    variant: str
    platform: str
    fee_displayed: float
    currency: str
    initial_capital: float
    reference_capital: float
    steps: tuple[ChallengeStep, ...]
    limits: ProfileLimits
    min_profitable_days_per_step: int
    profitable_day_definition: str
    evaluation_policy: str
    ambiguous_rules: tuple[AmbiguousRule, ...] = field(default_factory=tuple)
    notes: str = ""

    # -- lecture ------------------------------------------------------
    @classmethod
    def from_toml(cls, path: str | Path) -> "ChallengeProfile":
        """Charge et valide un profil depuis un fichier TOML."""
        source = Path(path)
        if not source.exists():
            raise ConfigurationError(f"challenge profile not found: {source}")
        try:
            payload = tomllib.loads(source.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(f"invalid TOML in {source}: {exc}") from exc
        return cls.from_dict(payload, source_path=str(source))

    @classmethod
    def from_dict(cls, payload: dict[str, Any], source_path: str | None = None) -> "ChallengeProfile":
        """Construit un profil a partir d'un dictionnaire deja lu."""
        try:
            status = ProfileStatus(payload["profile_status"])
        except KeyError as exc:
            raise ConfigurationError("challenge profile: missing profile_status") from exc
        except ValueError as exc:
            raise ConfigurationError(
                f"challenge profile: invalid profile_status {payload['profile_status']!r}"
            ) from exc

        program = payload.get("program", {})
        account = payload.get("account", {})
        limits_payload = payload.get("limits", {})
        evaluation = payload.get("evaluation", {})
        trading_days = payload.get("trading_days", {})

        steps = tuple(
            ChallengeStep(
                index=int(step["index"]),
                profit_target_percent=float(step["profit_target_percent"]),
                profit_target_amount=float(step["profit_target_amount"]),
                min_profitable_days=int(step["min_profitable_days"]),
                reference_capital=float(
                    step.get("reference_capital", account.get("reference_capital", 0.0))
                ),
            )
            for step in payload.get("steps", [])
        )
        if not steps:
            raise ConfigurationError("challenge profile: at least one step is required")

        rules = tuple(
            AmbiguousRule(
                id=str(rule["id"]),
                topic=str(rule.get("topic", "")),
                description=str(rule.get("description", "")),
                status=str(rule.get("status", "UNRESOLVED")),
                evaluation_policy=str(rule.get("evaluation_policy", "report_explicitly")),
                interpretations=tuple(
                    str(interp.get("id", ""))
                    for interp in rule.get("interpretations", [])
                ),
                assumed=str(rule.get("assumed", "")),
            )
            for rule in payload.get("ambiguous_rules", [])
        )

        profile = cls(
            profile_id=str(payload["profile_id"]),
            profile_version=str(payload.get("profile_version", "0.0.0")),
            profile_status=status,
            verified_on=str(payload.get("verified_on", "")),
            verified_by=str(payload.get("verified_by", "")),
            sources=tuple(payload.get("sources", ())),
            program_name=str(program.get("name", "")),
            variant=str(program.get("variant", "")),
            platform=str(program.get("platform", "")),
            fee_displayed=float(program.get("fee_displayed", 0.0)),
            currency=str(program.get("currency", "USD")),
            initial_capital=float(account.get("initial_capital", 0.0)),
            reference_capital=float(account.get("reference_capital", 0.0)),
            steps=steps,
            limits=ProfileLimits(
                max_daily_loss_percent=float(limits_payload.get("max_daily_loss_percent", 0.0)),
                max_daily_loss_amount=float(limits_payload.get("max_daily_loss_amount", 0.0)),
                max_total_loss_percent=float(limits_payload.get("max_total_loss_percent", 0.0)),
                max_total_loss_amount=float(limits_payload.get("max_total_loss_amount", 0.0)),
                drawdown_type=str(limits_payload.get("drawdown_type", "UNRESOLVED")),
                drawdown_basis=str(limits_payload.get("drawdown_basis", "UNRESOLVED")),
                daily_reset_time=str(limits_payload.get("daily_reset_time", "UNRESOLVED")),
                daily_reset_timezone=str(
                    limits_payload.get("daily_reset_timezone", "UNRESOLVED")
                ),
            ),
            min_profitable_days_per_step=int(
                trading_days.get("min_profitable_days_per_step", 0)
            ),
            profitable_day_definition=str(
                trading_days.get("profitable_day_definition", "UNRESOLVED")
            ),
            evaluation_policy=str(
                evaluation.get("policy", "most_restrictive_interpretation")
            ),
            ambiguous_rules=rules,
            notes=str(payload.get("notes", "")),
        )
        profile.validate()
        return profile

    # -- invariants ----------------------------------------------------
    def validate(self) -> None:
        """Verifie la coherence interne du profil."""
        if self.initial_capital <= 0:
            raise ConfigurationError("challenge profile: initial_capital must be > 0")
        if self.reference_capital <= 0:
            raise ConfigurationError("challenge profile: reference_capital must be > 0")
        if self.limits.max_daily_loss_amount <= 0:
            raise ConfigurationError("challenge profile: max_daily_loss_amount must be > 0")
        if self.limits.max_total_loss_amount <= 0:
            raise ConfigurationError("challenge profile: max_total_loss_amount must be > 0")
        for step in self.steps:
            if step.profit_target_amount <= 0:
                raise ConfigurationError(
                    f"challenge profile: step {step.index} profit_target_amount must be > 0"
                )
            if step.min_profitable_days < 0:
                raise ConfigurationError(
                    f"challenge profile: step {step.index} min_profitable_days must be >= 0"
                )
            expected = step.reference_capital * step.profit_target_percent / 100.0
            if abs(expected - step.profit_target_amount) > 0.01:
                raise ConfigurationError(
                    f"challenge profile: step {step.index} profit_target_amount "
                    f"({step.profit_target_amount}) is inconsistent with "
                    f"{step.profit_target_percent}% of {step.reference_capital} "
                    f"({expected:.2f})"
                )

    # -- etat ----------------------------------------------------------
    @property
    def unresolved_rules(self) -> tuple[AmbiguousRule, ...]:
        """Regles declarees mais non verifiees."""
        return tuple(rule for rule in self.ambiguous_rules if not rule.is_resolved)

    @property
    def blocking_rules(self) -> tuple[AmbiguousRule, ...]:
        """Regles dont l'echec interdit toute evaluation reelle."""
        return tuple(rule for rule in self.ambiguous_rules if rule.is_blocking)

    @property
    def allows_conclusion(self) -> bool:
        """Un profil non verifie ne peut pas produire de verdict."""
        return self.profile_status.allows_conclusion and not self.unresolved_rules

    def current_step(self, index: int) -> ChallengeStep:
        return self.steps[index]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_status": self.profile_status.value,
            "verified_on": self.verified_on,
            "verified_by": self.verified_by,
            "sources": list(self.sources),
            "program": {
                "name": self.program_name,
                "variant": self.variant,
                "platform": self.platform,
                "fee_displayed": self.fee_displayed,
                "currency": self.currency,
            },
            "initial_capital": self.initial_capital,
            "reference_capital": self.reference_capital,
            "steps": [step.to_dict() for step in self.steps],
            "limits": self.limits.to_dict(),
            "min_profitable_days_per_step": self.min_profitable_days_per_step,
            "profitable_day_definition": self.profitable_day_definition,
            "evaluation_policy": self.evaluation_policy,
            "ambiguous_rules": [rule.to_dict() for rule in self.ambiguous_rules],
            "allows_conclusion": self.allows_conclusion,
            "notes": self.notes,
        }
