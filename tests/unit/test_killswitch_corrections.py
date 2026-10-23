"""Tests du kill switch persistant (phase C, C5).

Un fichier obligatoire absent, illisible, corrompu ou de schema invalide doit
engager le kill switch (fail-closed). Le rearmement doit etre explicite et
trace.
"""

from __future__ import annotations

import json

import pytest

from etatmajor.core.errors import ConfigurationError
from etatmajor.risk.killswitch import KillSwitch


def test_a_missing_mandatory_file_engages_the_switch(tmp_path):
    switch = KillSwitch(tmp_path / "kill.json", required=True)
    assert switch.engaged is True
    assert switch.state_error is True


def test_a_missing_optional_file_starts_disarmed(tmp_path):
    # Un kill switch optionnel sans fichier n'a jamais ete engage : refuser de
    # demarrer serait inutilisable. Le caractere obligatoire est explicite.
    switch = KillSwitch(tmp_path / "kill.json")
    assert switch.engaged is False
    assert switch.state_error is False


def test_a_corrupted_file_engages_the_switch(tmp_path):
    path = tmp_path / "kill.json"
    path.write_text("{not json", encoding="utf-8")
    switch = KillSwitch(path)
    assert switch.engaged is True
    assert switch.state_error is True


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"engaged": "yes"},
        {"engaged": 1},
        {"engaged": True, "reason": 42},
        {"engaged": False, "engaged_ts_ns": "now"},
        {"engaged": False, "operator": "human"},  # cle inconnue
    ],
)
def test_an_invalid_schema_engages_the_switch(tmp_path, payload):
    path = tmp_path / "kill.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    switch = KillSwitch(path)
    assert switch.engaged is True
    assert switch.state_error is True


def test_an_unreadable_path_engages_the_switch(tmp_path):
    # Un repertoire ne peut pas etre lu comme un fichier JSON.
    path = tmp_path / "kill.json"
    path.mkdir()
    switch = KillSwitch(path)
    assert switch.engaged is True
    assert switch.state_error is True


def test_an_explicit_disarmed_state_is_honoured(tmp_path):
    path = tmp_path / "kill.json"
    path.write_text(json.dumps({"engaged": False}), encoding="utf-8")
    switch = KillSwitch(path)
    assert switch.engaged is False
    assert switch.state_error is False


def test_engaging_persists_the_state_atomically(tmp_path):
    path = tmp_path / "kill.json"
    path.write_text(json.dumps({"engaged": False}), encoding="utf-8")
    switch = KillSwitch(path)
    switch.engage("daily loss breached", 123)

    reloaded = KillSwitch(path)
    assert reloaded.engaged is True
    assert reloaded.state_error is False
    assert reloaded.state.reason == "daily loss breached"
    assert reloaded.state.engaged_ts_ns == 123
    assert reloaded.state.engagement_count == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_reset_requires_a_reason_and_is_traced(tmp_path):
    path = tmp_path / "kill.json"
    switch = KillSwitch(path)
    switch.engage("manual test", 1)

    with pytest.raises(ConfigurationError):
        switch.reset("", 2)
    with pytest.raises(ConfigurationError):
        switch.reset("   ", 2)
    assert switch.engaged is True

    switch.reset("incident reviewed", 2, "ops")
    assert switch.engaged is False
    assert switch.state.engaged_ts_ns == 0
    assert switch.state.last_reset_ts_ns == 2
    assert switch.state.last_reset_reason == "incident reviewed (operator: ops)"

    reloaded = KillSwitch(path)
    assert reloaded.engaged is False
    assert reloaded.state.last_reset_ts_ns == 2
    assert "incident reviewed" in reloaded.state.last_reset_reason


def test_a_persistence_failure_keeps_the_switch_engaged(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    # Le parent du fichier de kill switch est un fichier : l'ecriture echoue.
    switch = KillSwitch(blocker / "kill.json", required=True)
    assert switch.engaged is True

    with pytest.raises(ConfigurationError):
        switch.reset("try reset", 1)

    assert switch.engaged is True
    assert switch.state_error is True
    assert KillSwitch(blocker / "kill.json", required=True).engaged is True
