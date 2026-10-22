"""Tests de la vue bornee VisibleBars (correction C1).

La vue remplace la copie complete de l'historique, qui rendait le rejeu
quadratique. Ces tests verrouillent deux proprietes : le cout constant et
l'impossibilite de lire une bougie future.
"""

from __future__ import annotations

import pytest

from etatmajor.data.models import Bar
from etatmajor.strategies.base import VisibleBars


def make_bars(count: int) -> list[Bar]:
    return [
        Bar(
            ts_open_ns=index,
            ts_close_ns=index + 1,
            open=1.0 + index,
            high=1.5 + index,
            low=0.5 + index,
            close=1.2 + index,
        )
        for index in range(count)
    ]


def test_length_is_the_visible_limit():
    bars = make_bars(100)
    view = VisibleBars(bars, 10)
    assert len(view) == 10
    assert view.limit == 10
    assert view.total == 100


def test_limit_is_capped_at_the_underlying_length():
    view = VisibleBars(make_bars(5), 50)
    assert len(view) == 5


def test_negative_limit_is_refused():
    with pytest.raises(ValueError):
        VisibleBars(make_bars(5), -1)


def test_indexing_returns_the_visible_bars():
    bars = make_bars(100)
    view = VisibleBars(bars, 10)
    assert view[0] is bars[0]
    assert view[9] is bars[9]


def test_negative_index_is_relative_to_the_window():
    bars = make_bars(100)
    view = VisibleBars(bars, 10)
    assert view[-1] is bars[9]
    assert view[-10] is bars[0]


def test_accessing_a_future_bar_raises_index_error():
    """La garantie anti-look-ahead ne depend pas de la bonne foi du code."""
    bars = make_bars(100)
    view = VisibleBars(bars, 10)
    with pytest.raises(IndexError):
        view[10]
    with pytest.raises(IndexError):
        view[-11]
    with pytest.raises(IndexError):
        view[99]


def test_iteration_yields_only_visible_bars():
    bars = make_bars(100)
    view = VisibleBars(bars, 7)
    assert [bar.ts_open_ns for bar in view] == list(range(7))
    assert len(list(view)) == 7


def test_slicing_is_bounded_by_the_window():
    bars = make_bars(100)
    view = VisibleBars(bars, 7)
    assert len(view[:]) == 7
    assert len(view[0:50]) == 7
    assert [bar.ts_open_ns for bar in view[2:4]] == [2, 3]


def test_last_returns_only_visible_bars():
    bars = make_bars(100)
    view = VisibleBars(bars, 7)
    assert [bar.ts_open_ns for bar in view.last(3)] == [4, 5, 6]
    assert view.last(100) == tuple(bars[:7])
    assert view.last(0) == ()
    assert view.last(-1) == ()


def test_the_view_does_not_copy_the_history():
    """Construction O(1) : aucune liste materialisee n'est conservee."""
    bars = make_bars(1_000_000)
    view = VisibleBars(bars, 500_000)
    assert len(view) == 500_000
    assert view[0] is bars[0]
    assert view[-1] is bars[499_999]


def test_the_view_is_read_only():
    bars = make_bars(10)
    view = VisibleBars(bars, 5)
    with pytest.raises(TypeError):
        view[0] = bars[9]  # type: ignore[index]
