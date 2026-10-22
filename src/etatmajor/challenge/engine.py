"""Challenge Engine : suivi de l'etat du challenge et production d'un verdict.

Le moteur ne repond pas a « combien aurions-nous gagne ? » mais a « aurions-nous
respecte les regles du challenge, et jusqu'ou ? ».

Regles de conception
--------------------
* un profil non verifie ne produit **jamais** un verdict de conformite : le
  verdict est ``INVALID`` et un etat *indicatif* est fourni a cote ;
* une regle ambigue est evaluee sous toutes ses interpretations ; le verdict
  le plus defavorable l'emporte ; ``PASSED`` n'est prononce que si toutes les
  interpretations passent ;
* le compteur quotidien suit le profil (heure de reinitialisation) et
  l'hypothese employee est rappelee dans le verdict ;
* le moteur ne modifie jamais le portefeuille : il observe et il juge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.models import AccountState, ChallengeState
from .profile import ChallengeProfile

NANOSECONDS_PER_DAY = 86_400_000_000_000


@dataclass
class InterpretationResult:
    """Resultat d'une interpretation d'une regle ambigue."""

    interpretation_id: str
    daily_loss: float
    total_loss: float
    daily_limit_breached: bool
    total_limit_breached: bool
    state: ChallengeState
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "interpretation_id": self.interpretation_id,
            "daily_loss": self.daily_loss,
            "total_loss": self.total_loss,
            "daily_limit_breached": self.daily_limit_breached,
            "total_limit_breached": self.total_limit_breached,
            "state": self.state.value,
            "reason": self.reason,
        }


@dataclass
class ChallengeVerdict:
    """Verdict du challenge simule."""

    state: ChallengeState
    indicative_state: ChallengeState
    reasons: list[str] = field(default_factory=list)
    step_index: int = 1
    steps_completed: int = 0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    max_daily_loss: float = 0.0
    max_total_loss: float = 0.0
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    profitable_days: int = 0
    trading_days: int = 0
    distance_to_target: float = 0.0
    distance_to_daily_limit: float = 0.0
    distance_to_total_limit: float = 0.0
    interpretations: list[InterpretationResult] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    @property
    def is_conclusive(self) -> bool:
        return self.state.is_conclusive

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "indicative_state": self.indicative_state.value,
            "is_conclusive": self.is_conclusive,
            "reasons": list(self.reasons),
            "step_index": self.step_index,
            "steps_completed": self.steps_completed,
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.total_pnl,
            "max_daily_loss": self.max_daily_loss,
            "max_total_loss": self.max_total_loss,
            "peak_equity": self.peak_equity,
            "max_drawdown": self.max_drawdown,
            "profitable_days": self.profitable_days,
            "trading_days": self.trading_days,
            "distance_to_target": self.distance_to_target,
            "distance_to_daily_limit": self.distance_to_daily_limit,
            "distance_to_total_limit": self.distance_to_total_limit,
            "interpretations": [i.to_dict() for i in self.interpretations],
            "assumptions": list(self.assumptions),
        }


class ChallengeEngine:
    """Suit l'etat du challenge et produit un verdict."""

    def __init__(
        self,
        profile: ChallengeProfile,
        initial_capital: float | None = None,
        reset_hour_utc: int = 0,
    ) -> None:
        self.profile = profile
        self.initial_capital = (
            initial_capital if initial_capital is not None else profile.initial_capital
        )
        self.reset_hour_utc = reset_hour_utc
        self.state = ChallengeState.READY
        self.step_index = 0
        self.trading_days = 0
        self.profitable_days = 0
        self.peak_equity = self.initial_capital
        self.max_drawdown = 0.0
        self.max_daily_loss = 0.0
        self.max_total_loss = 0.0
        self.current_day_key: int | None = None
        self._day_start_balance: float = self.initial_capital
        self._day_start_equity: float = self.initial_capital
        self._day_peak_equity: float = self.initial_capital
        self._day_realized_pnl: float = 0.0
        self._last_balance: float = self.initial_capital
        self._last_equity: float = self.initial_capital
        self._last_ts_ns: int = 0
        self._reasons: list[str] = []

    # -- observation ---------------------------------------------------
    def observe(self, ts_ns: int, account: AccountState) -> None:
        """Enregistre un etat du compte et met a jour le suivi du challenge."""
        if self.state is ChallengeState.READY:
            self.state = ChallengeState.RUNNING

        day_key = self._day_key(ts_ns)
        if self.current_day_key is None:
            self.current_day_key = day_key
            self._day_start_balance = account.balance
            self._day_start_equity = account.equity
            self._day_peak_equity = account.equity
            self._day_realized_pnl = 0.0
        elif day_key != self.current_day_key:
            # Cloture de la journee ecoulee : le PnL realise de la journee est
            # la variation du solde (il ne depend pas de l'equity latente).
            self.trading_days += 1
            self._day_realized_pnl = self._last_balance - self._day_start_balance
            if self._day_realized_pnl > 0:
                self.profitable_days += 1
            self.current_day_key = day_key
            self._day_start_balance = account.balance
            self._day_start_equity = account.equity
            self._day_peak_equity = account.equity
            self._day_realized_pnl = 0.0

        self._last_ts_ns = ts_ns
        self._last_balance = account.balance
        self._last_equity = account.equity
        self._day_peak_equity = max(self._day_peak_equity, account.equity)
        self.peak_equity = max(self.peak_equity, account.equity)
        drawdown = self.peak_equity - account.equity
        self.max_drawdown = max(self.max_drawdown, drawdown)

    def finalize(self) -> None:
        """Cloture de la journee en cours a la fin du replay.

        Sans cet appel, la derniere journee de la campagne ne serait pas
        comptee : le nombre de jours de trading et de jours profitables serait
        sous-estime d'un jour.
        """
        if self.current_day_key is None:
            return
        if self.state is ChallengeState.RUNNING:
            self.trading_days += 1
            self._day_realized_pnl = self._last_balance - self._day_start_balance
            if self._day_realized_pnl > 0:
                self.profitable_days += 1

    def _day_key(self, ts_ns: int) -> int:
        """Cle de journee, decalee par l'heure de reinitialisation du profil."""
        offset = self.reset_hour_utc * 3_600_000_000_000
        return (ts_ns - offset) // NANOSECONDS_PER_DAY

    # -- evaluations ---------------------------------------------------
    def _daily_loss_balance(self) -> float:
        """Perte de la journee, lecture statique (solde)."""
        return max(0.0, self._day_start_balance - self._last_balance)

    def _daily_loss_equity(self) -> float:
        """Perte de la journee, lecture trailing (equity, depuis le pic du jour)."""
        return max(0.0, self._day_peak_equity - self._last_equity)

    def _total_loss_balance(self) -> float:
        return max(0.0, self.profile.reference_capital - self._last_balance)

    def _total_loss_equity(self) -> float:
        return max(0.0, self.profile.reference_capital - self._last_equity)

    def _evaluate_interpretation(
        self, interpretation_id: str, daily_loss: float, total_loss: float
    ) -> InterpretationResult:
        limits = self.profile.limits
        daily_breach = daily_loss >= limits.max_daily_loss_amount
        total_breach = total_loss >= limits.max_total_loss_amount

        if daily_breach:
            state = ChallengeState.FAILED
            reason = (
                f"daily loss {daily_loss:.2f} reached the limit "
                f"{limits.max_daily_loss_amount:.2f}"
            )
        elif total_breach:
            state = ChallengeState.FAILED
            reason = (
                f"total loss {total_loss:.2f} reached the limit "
                f"{limits.max_total_loss_amount:.2f}"
            )
        else:
            state, reason = self._evaluate_progress()

        return InterpretationResult(
            interpretation_id=interpretation_id,
            daily_loss=daily_loss,
            total_loss=total_loss,
            daily_limit_breached=daily_breach,
            total_limit_breached=total_breach,
            state=state,
            reason=reason,
        )

    def _evaluate_progress(self) -> tuple[ChallengeState, str]:
        """Verdict de progression, independant de la lecture des limites."""
        step = self.profile.current_step(self.step_index)
        target = step.reference_capital + step.profit_target_amount
        profit = self._last_equity - step.reference_capital
        if profit >= step.profit_target_amount:
            if self.profitable_days >= step.min_profitable_days:
                if self.step_index + 1 < len(self.profile.steps):
                    self.step_index += 1
                    return (
                        ChallengeState.RUNNING,
                        f"step {step.index} validated, moving to step {self.step_index + 1}",
                    )
                return (
                    ChallengeState.PASSED,
                    f"all steps validated (target {step.profit_target_amount:.2f} reached)",
                )
            missing = step.min_profitable_days - self.profitable_days
            return (
                ChallengeState.RUNNING,
                f"step {step.index} profit target reached, "
                f"{missing} profitable day(s) still required",
            )
        return (
            ChallengeState.RUNNING,
            f"step {step.index} in progress: {profit:.2f} / "
            f"{step.profit_target_amount:.2f} ({target:.2f} equity required)",
        )

    # -- verdict --------------------------------------------------------
    def evaluate(self) -> ChallengeVerdict:
        """Produit le verdict du challenge."""
        reasons: list[str] = []
        assumptions: list[str] = []

        if not self.profile.limits.reset_time_is_resolved:
            assumptions.append(
                f"daily reset hour not documented in the profile: "
                f"{self.reset_hour_utc}:00 UTC is used (assumption, rule V2)"
            )
        if not self.profile.limits.daily_basis_is_resolved:
            assumptions.append(
                "daily loss basis not documented (rule V1): both the static "
                "balance reading and the trailing equity reading are evaluated"
            )
        if self.profile.profitable_day_definition == "UNRESOLVED":
            assumptions.append(
                "profitable day definition not documented (rule V3): a day counts "
                "as profitable when its realised net PnL is strictly positive"
            )

        interpretations = [
            self._evaluate_interpretation(
                "balance_static", self._daily_loss_balance(), self._total_loss_balance()
            ),
            self._evaluate_interpretation(
                "equity_trailing", self._daily_loss_equity(), self._total_loss_equity()
            ),
        ]

        # Le verdict le plus defavorable l'emporte.
        order = {
            ChallengeState.FAILED: 0,
            ChallengeState.INVALID: 1,
            ChallengeState.REVIEW_REQUIRED: 2,
            ChallengeState.RUNNING: 3,
            ChallengeState.PASSED: 4,
        }
        indicative = min(
            (i.state for i in interpretations), key=lambda s: order[s]
        )
        for interpretation in interpretations:
            # La raison de l'interpretation la plus restrictive est toujours
            # rapportee ; les autres ne le sont que si elles different.
            if interpretation.state is indicative or interpretation.reason:
                if interpretation.state is not indicative:
                    reasons.append(
                        f"interpretation {interpretation.interpretation_id}: "
                        f"{interpretation.reason}"
                    )

        # Le verdict officiel exige un profil verifiable.
        if not self.profile.allows_conclusion:
            state = ChallengeState.INVALID
            reasons.append(
                f"profile {self.profile.profile_id} v{self.profile.profile_version} is "
                f"{self.profile.profile_status.value}: "
                f"{len(self.profile.unresolved_rules)} unresolved rule(s) "
                f"({', '.join(rule.id for rule in self.profile.unresolved_rules)}); "
                f"no conformance verdict can be issued"
            )
            for rule in self.profile.blocking_rules:
                reasons.append(
                    f"rule {rule.id} ({rule.topic}) is blocking for a real evaluation"
                )
        else:
            state = indicative

        indicative_result = next(
            (i for i in interpretations if i.state is indicative), None
        )
        if indicative_result is not None and indicative_result.reason:
            reasons.insert(
                0,
                f"interpretation {indicative_result.interpretation_id}: "
                f"{indicative_result.reason}",
            )

        step = self.profile.current_step(self.step_index)
        daily_loss = max(i.daily_loss for i in interpretations)
        total_loss = max(i.total_loss for i in interpretations)

        return ChallengeVerdict(
            state=state,
            indicative_state=indicative,
            reasons=reasons,
            step_index=step.index,
            steps_completed=self.step_index,
            daily_pnl=self._last_equity - self._day_start_equity,
            total_pnl=self._last_equity - self.initial_capital,
            max_daily_loss=self.max_daily_loss,
            max_total_loss=self.max_total_loss,
            peak_equity=self.peak_equity,
            max_drawdown=self.max_drawdown,
            profitable_days=self.profitable_days,
            trading_days=self.trading_days,
            distance_to_target=max(
                0.0, step.profit_target_amount - (self._last_equity - step.reference_capital)
            ),
            distance_to_daily_limit=max(
                0.0, self.profile.limits.max_daily_loss_amount - daily_loss
            ),
            distance_to_total_limit=max(
                0.0, self.profile.limits.max_total_loss_amount - total_loss
            ),
            interpretations=interpretations,
            assumptions=assumptions,
        )

    # -- garde-fou pour le RiskGovernor --------------------------------
    def blocks_new_risk(self) -> tuple[bool, str]:
        """Indique si une nouvelle prise de risque doit etre refusee.

        Un profil non verifiable (``INVALID``) **interdit de conclure**, pas de
        simuler : la recherche reste possible, mais aucun rapport ne pourra
        declarer la campagne conforme. Un challenge ``FAILED``, en revanche,
        ferme la porte a toute nouvelle prise de risque.
        """
        verdict = self.evaluate()
        if verdict.state is ChallengeState.FAILED or verdict.indicative_state is ChallengeState.FAILED:
            # Un challenge rate, meme sous un profil non verifiable, ferme la
            # porte : on ne prend pas de risque sur un compte deja casse.
            return True, (
                f"the challenge is FAILED (official state {verdict.state.value}, "
                f"indicative state {verdict.indicative_state.value}): "
                f"no new exposure is allowed"
            )
        if verdict.distance_to_daily_limit <= 0:
            return True, (
                "the daily loss limit is reached: no new exposure is allowed"
            )
        if verdict.distance_to_total_limit <= 0:
            return True, (
                "the total loss limit is reached: no new exposure is allowed"
            )
        return False, ""
