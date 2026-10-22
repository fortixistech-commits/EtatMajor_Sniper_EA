"""Contrat de stratégie et vue bornée de l'historique.

Anti-look-ahead : la stratégie ne reçoit que les bougies dont la clôture est
antérieure ou égale à l'instant simulé de la décision. Cette garantie est
appliquée par construction : la vue `VisibleBars` est **bornée** et n'expose
aucune barre au-delà de la limite, sans jamais copier l'historique.

Performance : la copie complète de l'historique visible à chaque bougie rendait
le rejeu quadratique (43 µs/bougie à 240 bougies contre 114 µs/bougie à
20 000). `VisibleBars` rend l'opération O(1) : elle ne copie rien.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from ..core.clock import SimClock
from ..core.events import Fill, Signal
from ..data.models import Bar
from ..execution.accounting import PortfolioSnapshot


class VisibleBars(Sequence):
    """Fenêtre en lecture seule sur les bougies visibles.

    La vue ne stocke que la séquence sous-jacente et une limite. Le coût
    d'accès est constant : aucune copie de l'historique n'est réalisée, ce qui
    supprime le comportement quadratique du rejeu.

    Les index négatifs sont relatifs à la **fin de la fenêtre** (comme pour
    une séquence Python). Un index qui sort de la fenêtre lève une
    `IndexError` : il est impossible de lire une bougie future.
    """

    __slots__ = ("_bars", "_limit")

    def __init__(self, bars: Sequence[Bar], limit: int) -> None:
        if limit < 0:
            raise ValueError(f"visible limit must be >= 0 (got {limit})")
        self._bars = bars
        self._limit = min(limit, len(bars))

    # -- introspection ------------------------------------------------
    @property
    def limit(self) -> int:
        """Nombre de bougies visibles."""
        return self._limit

    @property
    def total(self) -> int:
        """Nombre de bougies de la séquence sous-jacente."""
        return len(self._bars)

    def __len__(self) -> int:
        return self._limit

    def __repr__(self) -> str:
        return f"VisibleBars(limit={self._limit}, total={self.total})"

    # -- acces --------------------------------------------------------
    def _resolve(self, index: int) -> int:
        resolved = index if index >= 0 else self._limit + index
        if resolved < 0 or resolved >= self._limit:
            raise IndexError(
                f"index {index} is outside the visible window "
                f"[0, {self._limit}) : no future bar is reachable"
            )
        return resolved

    def __getitem__(self, index):  # type: ignore[override]
        if isinstance(index, slice):
            start, stop, step = index.indices(self._limit)
            return tuple(self._bars[i] for i in range(start, stop, step))
        return self._bars[self._resolve(index)]

    def __iter__(self):
        for index in range(self._limit):
            yield self._bars[index]

    def last(self, count: int) -> tuple[Bar, ...]:
        """Les ``count`` dernieres bougies visibles, sans copie inutile."""
        if count <= 0:
            return ()
        count = min(count, self._limit)
        start = self._limit - count
        return tuple(self._bars[start : self._limit])


@dataclass(frozen=True)
class StrategyContext:
    """Tout ce qu'une stratégie est autorisée à voir au moment de la décision."""

    index: int
    bar: Bar
    visible_bars: VisibleBars
    clock: SimClock
    portfolio: PortfolioSnapshot
    recent_fills: tuple[Fill, ...] = field(default_factory=tuple)
    final: bool = False

    @property
    def close(self) -> float:
        return self.bar.close

    def last_bars(self, count: int) -> tuple[Bar, ...]:
        """Les ``count`` dernières bougies visibles."""
        return self.visible_bars.last(count)

    def position_quantity(self, symbol: str) -> float:
        for position in self.portfolio.positions:
            if position["symbol"] == symbol:
                return float(position["quantity"])
        return 0.0


@runtime_checkable
class Strategy(Protocol):
    """Interface implémentée par toutes les stratégies de la plateforme."""

    strategy_id: str
    strategy_version: str

    def on_start(self, context: StrategyContext) -> None:
        """Appelée une fois avant la première bougie."""
        ...

    def on_bar(self, context: StrategyContext) -> Sequence[Signal]:
        """Appelée à la clôture de chaque bougie ; renvoie zéro ou plus de propositions."""
        ...

    def on_stop(self, context: StrategyContext) -> None:
        """Appelée une fois après la dernière bougie (contexte ``final=True``)."""
        ...
