"""Challenge Engine : suivi de l'etat du challenge et production d'un verdict.

Le moteur ne repond pas a « combien aurions-nous gagne ? » mais a « aurions-nous
respecte les regles du challenge, et jusqu'ou ? ».

Regles de conception
-------------------
* **observer** et **juger** sont deux operations distinctes. ``observe`` fait
  progresser l'etat (journees, maxima de perte, etapes validees) ; ``evaluate``
  lit l'etat et ne le modifie jamais. Un meme etat de compte evalue plusieurs
  fois produit donc exactement le meme verdict ;
* une etape n'est validee que si ses propres regles sont satisfaites, et au
  plus une etape est franchie par observation. Deux cibles franchies dans la
  meme observation ne permettent pas de sauter l'etape intermediaire ;
* une violation fatale (perte journaliere ou perte totale) est **terminale** :
  elle reste enregistree meme si le solde ou l'equity remonte ensuite ;
* un profil non verifie ne produit **jamais** un verdict de conformite : le
  verdict est ``INVALID`` et un etat *indicatif* est fourni a cote ;
* une regle ambigue est evaluee sous toutes ses interpretations ; le verdict
  le plus defavorable l'emporte ; ``PASSED`` n'est prononce que si toutes les
  interpretations passent ;
* le compteur quotidien suit le profil (heure de reinitialisation) et
  l'hypothese employee est rappelee dans le verdict ;
* le moteur ne modifie jamais le portefeuille : il observe et il juge.

Limites du modele OHLC
----------------------
Une observation est faite a la cloture d'une bougie. Une violation qui
survient puis se resorbe *a l'interieur* d'une meme bougie ne peut pas etre
detectee avec des donnees OHLC : le moteur ne pretend pas reproduire une
regle intrabar. Seules les violations visibles aux instants d'observation
sont evaluees. Cette limite est explicite dans le verdict (``model_limits``)
et dans la documentation de la phase C.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.errors import ConfigurationError
from ..core.models import AccountState, ChallengeState
from .profile import ChallengeProfile

NANOSECONDS_PER_DAY = 86_400_000_000_000

MODEL_LIMIT_INTRABAR = (
    "OHLC observations only: an intrabar breach that recovers before the bar "
    "close cannot be detected and is not simulated"
)


@dataclass(frozen=True)
class FailureRecord:
    """Violation fatale enregistree, conservée jusqu'a la fin de la campagne."""

    kind: str
    basis: str
    amount: float
    limit: float
    ts_ns: int
    step_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "basis": self.basis,
            "amount": self.amount,
            "limit": self.limit,
            "ts_ns": self.ts_ns,
            "step_index": self.step_index,
            "terminal": True,
        }


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
    failures: list[FailureRecord] = field(default_factory=list)
    ignored_observations: int = 0
    model_limits: list[str] = field(default_factory=list)

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
            "failures": [failure.to_dict() for failure in self.failures],
            "ignored_observations": self.ignored_observations,
            "model_limits": list(self.model_limits),
        }


class ChallengeEngine:
    """Suit l'etat du challenge et produit un verdict."""

    def __init__(
        self,
        profile: ChallengeProfile,
        initial_capital: float | None = None,
        reset_hour_utc: int = 0,
    ) -> None:
        if (
            isinstance(reset_hour_utc, bool)
            or not isinstance(reset_hour_utc, int)
            or not 0 <= reset_hour_utc <= 23
        ):
            raise ConfigurationError(
                "challenge reset hour must be an integer between 0 and 23"
            )
        self.profile = profile
        self.initial_capital = (
            initial_capital if initial_capital is not None else profile.initial_capital
        )
        self.reset_hour_utc = reset_hour_utc
        self.events: list[dict[str, Any]] = []
        self.state = ChallengeState.READY
        self.step_index = 0
        self.trading_days = 0
        self.profitable_days = 0
        self.peak_equity = self.initial_capital
        self.max_drawdown = 0.0
        self.max_daily_loss = 0.0
        self.max_total_loss = 0.0
        self.current_day_key: int | None = None
        self.ignored_observations = 0
        self._day_start_balance: float = self.initial_capital
        self._day_start_equity: float = self.initial_capital
        self._day_peak_equity: float = self.initial_capital
        self._day_realized_pnl: float = 0.0
        self._last_balance: float = self.initial_capital
        self._last_equity: float = self.initial_capital
        self._last_ts_ns: int = 0
        self._last_signature: tuple[int, float, float] | None = None
        self._failures: list[FailureRecord] = []
        self._passed = False
        self._finalized = False

    # -- observation ---------------------------------------------------
    def observe(self, ts_ns: int, account: AccountState) -> None:
        """Enregistre un etat du compte et met a jour le suivi du challenge.

        Cette methode est la seule a faire progresser l'etat. Elle est
        idempotente pour une observation identique (meme horodatage, memes
        valeurs) et ignore les observations en retard ou contradictoires au
        lieu de produire un etat dependant de l'ordre d'arrivee.
        """
        if self.state is ChallengeState.READY:
            self.state = ChallengeState.RUNNING

        signature = (int(ts_ns), float(account.balance), float(account.equity))

        if self._last_ts_ns and ts_ns < self._last_ts_ns:
            # Evenement en retard : il ne peut plus modifier un etat deja vu.
            self.ignored_observations += 1
            return
        if signature == self._last_signature:
            # Observation dupliquee : aucun effet supplementaire.
            return
        if self._last_signature is not None and ts_ns == self._last_ts_ns:
            # Deux etats differents au meme instant : le premier fait foi.
            self.ignored_observations += 1
            return

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
        self._last_signature = signature
        self._last_balance = account.balance
        self._last_equity = account.equity
        self._day_peak_equity = max(self._day_peak_equity, account.equity)
        self.peak_equity = max(self.peak_equity, account.equity)
        drawdown = self.peak_equity - account.equity
        self.max_drawdown = max(self.max_drawdown, drawdown)

        self._update_loss_tracking()
        self._maybe_advance_step()

    def drain_events(self) -> list[dict[str, Any]]:
        """Return and clear the transitions recorded since the last call."""
        events = self.events
        self.events = []
        return events

    def finalize(self) -> None:
        """Cloture de la journee en cours a la fin du replay.

        Sans cet appel, la derniere journee de la campagne ne serait pas
        comptee : le nombre de jours de trading et de jours profitables serait
        sous-estime d'un jour. L'appel est idempotent.
        """
        if self.current_day_key is None or self._finalized:
            return
        self._finalized = True
        # La derniere journee existe, qu'elle ait echoue, reussi ou soit en
        # cours : elle est comptee pour le rapport. Cela ne retire jamais un
        # echec terminal deja enregistre.
        self.trading_days += 1
        self._day_realized_pnl = self._last_balance - self._day_start_balance
        if self._day_realized_pnl > 0:
            self.profitable_days += 1
        # La journee finalisee peut etre celle qui apporte le dernier jour
        # profitable requis : une seule etape peut alors etre validee.
        self._maybe_advance_step()

    def _day_key(self, ts_ns: int) -> int:
        """Cle de journee, decalee par l'heure de reinitialisation du profil."""
        offset = self.reset_hour_utc * 3_600_000_000_000
        return (ts_ns - offset) // NANOSECONDS_PER_DAY

    # -- suivi des pertes ----------------------------------------------
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

    def _update_loss_tracking(self) -> None:
        """Met a jour les maxima de perte et enregistre les violations fatales.

        Les maxima sont mis a jour a chaque observation, y compris apres un
        echec terminal : une recuperation ne reecrit pas l'histoire. En
        revanche, une violation deja enregistree n'est jamais retiree.
        """
        daily = {
            "balance_static": self._daily_loss_balance(),
            "equity_trailing": self._daily_loss_equity(),
        }
        total = {
            "balance_static": self._total_loss_balance(),
            "equity_trailing": self._total_loss_equity(),
        }
        self.max_daily_loss = max(self.max_daily_loss, *daily.values())
        self.max_total_loss = max(self.max_total_loss, *total.values())

        if self._failures:
            return

        limits = self.profile.limits
        for basis, amount in daily.items():
            if amount >= limits.max_daily_loss_amount:
                failure = FailureRecord(
                    kind="daily_loss",
                    basis=basis,
                    amount=amount,
                    limit=limits.max_daily_loss_amount,
                    ts_ns=self._last_ts_ns,
                    step_index=self.step_index,
                )
                self._failures.append(failure)
                self.events.append({"kind": "failure", "failure": failure.to_dict()})
        for basis, amount in total.items():
            if amount >= limits.max_total_loss_amount:
                failure = FailureRecord(
                    kind="total_loss",
                    basis=basis,
                    amount=amount,
                    limit=limits.max_total_loss_amount,
                    ts_ns=self._last_ts_ns,
                    step_index=self.step_index,
                )
                self._failures.append(failure)
                self.events.append({"kind": "failure", "failure": failure.to_dict()})

    def _failed_or_passed(self) -> bool:
        return bool(self._failures) or self._passed

    def _maybe_advance_step(self) -> None:
        """Valide au plus une etape, uniquement sur une observation nouvelle."""
        if self._failed_or_passed():
            return
        step = self.profile.current_step(self.step_index)
        profit = self._last_equity - step.reference_capital
        if profit < step.profit_target_amount:
            return
        if self.profitable_days < step.min_profitable_days:
            return
        if self.step_index + 1 < len(self.profile.steps):
            self.step_index += 1
            self.events.append(
                {
                    "kind": "step_advanced",
                    "ts_ns": self._last_ts_ns,
                    "steps_completed": self.step_index,
                    "step_index": self.profile.current_step(self.step_index).index,
                }
            )
        else:
            self._passed = True
            self.events.append(
                {
                    "kind": "passed",
                    "ts_ns": self._last_ts_ns,
                    "steps_completed": len(self.profile.steps),
                }
            )

    # -- evaluations (lecture pure) ------------------------------------
    def _progress_state(
        self, include_failure: bool = True
    ) -> tuple[ChallengeState, str]:
        """Etat de progression courant, sans mutation."""
        if include_failure and self._failures:
            return ChallengeState.FAILED, self._failure_reason(self._failures[0])
        if self._passed:
            step = self.profile.current_step(len(self.profile.steps) - 1)
            return (
                ChallengeState.PASSED,
                f"all steps validated (target {step.profit_target_amount:.2f} reached)",
            )
        step = self.profile.current_step(self.step_index)
        target = step.reference_capital + step.profit_target_amount
        profit = self._last_equity - step.reference_capital
        if profit >= step.profit_target_amount:
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

    def _failure_reason(self, failure: FailureRecord) -> str:
        label = "daily loss" if failure.kind == "daily_loss" else "total loss"
        return (
            f"terminal {label} failure ({failure.basis} reading) at ts "
            f"{failure.ts_ns}: {failure.amount:.2f} reached the limit "
            f"{failure.limit:.2f}; the failure is final and cannot be cleared "
            f"by a later recovery"
        )

    def _evaluate_interpretation(
        self, interpretation_id: str, daily_loss: float, total_loss: float
    ) -> InterpretationResult:
        limits = self.profile.limits
        daily_breach = daily_loss >= limits.max_daily_loss_amount
        total_breach = total_loss >= limits.max_total_loss_amount
        progress_state, progress_reason = self._progress_state(include_failure=False)

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
            state = progress_state
            reason = progress_reason

        return InterpretationResult(
            interpretation_id=interpretation_id,
            daily_loss=daily_loss,
            total_loss=total_loss,
            daily_limit_breached=daily_breach,
            total_limit_breached=total_breach,
            state=state,
            reason=reason,
        )

    # -- verdict --------------------------------------------------------
    def evaluate(self) -> ChallengeVerdict:
        """Produit le verdict du challenge (lecture pure, idempotente)."""
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

        # Le verdict le plus defavorable l'emporte. Une violation terminale
        # enregistree reste FAILED meme si les lectures courantes sont revenues
        # sous les limites.
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
        if self._failures:
            indicative = ChallengeState.FAILED
        elif self._passed:
            indicative = ChallengeState.PASSED

        for failure in self._failures:
            reasons.append(self._failure_reason(failure))

        for interpretation in interpretations:
            # La raison de l'interpretation la plus restrictive est toujours
            # rapportee ; les autres ne le sont que si elles divergent.
            if interpretation.state is not indicative and interpretation.state is not ChallengeState.FAILED:
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
                0 if not self._failures else len(self._failures),
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
            steps_completed=(
                len(self.profile.steps) if self._passed else self.step_index
            ),
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
            failures=list(self._failures),
            ignored_observations=self.ignored_observations,
            model_limits=[MODEL_LIMIT_INTRABAR],
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
