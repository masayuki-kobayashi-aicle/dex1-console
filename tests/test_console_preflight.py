import json

from dex1_rs485.config import Config
from dex1_rs485.console import Console
from dex1_rs485.i18n import t
from dex1_rs485.preflight import PREFLIGHT_STAGES, run_preflight
from dex1_rs485.prompter import ScriptedPrompter


def test_preflight_passes_on_a_healthy_mock(ctrl):
    io = ScriptedPrompter([""])
    stages = run_preflight(ctrl, io)
    assert len(stages) == PREFLIGHT_STAGES and all(s.ok for s in stages), [s for s in stages if not s.ok]


def test_preflight_stops_when_the_finger_is_held_away_from_the_closed_position(ctrl, hand):
    hand.q, hand.stuck = 3.0, True  # something holds the finger; the self-closing stops far from closed
    io = ScriptedPrompter([])
    stages = run_preflight(ctrl, io)
    assert stages[-1].name == "4 calibration" and not stages[-1].ok and io.answers == []  # no look is asked for


def test_preflight_stops_when_the_hand_is_silent(ctrl, hand):
    hand.drop_replies = 100
    stages = run_preflight(ctrl, ScriptedPrompter([]))
    assert stages[-1].name == "2 link" and not stages[-1].ok


def test_preflight_closes_by_itself_and_asks_only_for_a_look(ctrl):
    io = ScriptedPrompter([""])
    stages = run_preflight(ctrl, io)
    assert io.answers == []  # one question, and it is the visual check
    assert [s for s in io.said if s.lstrip().startswith(("Visual check", "Safety"))] == [t("cal_ask")]
    assert stages[3].ok and "closed by itself" in stages[3].detail


def test_a_no_to_the_visual_check_fails_and_restores_the_zero(ctrl):
    ctrl.link.zero_rad = 0.25
    stages = run_preflight(ctrl, ScriptedPrompter(["n"]))
    assert stages[-1].name == "4 calibration" and not stages[-1].ok and len(stages) == 4
    assert ctrl.link.zero_rad == 0.25


def test_console_commands(ctrl, tmp_path):
    cfg = Config(log_dir=str(tmp_path))
    io = ScriptedPrompter(["h", "bogus", "g abc", "g 99", "t 2", "", "s", "", "l on", "c", "l off", "q"])
    Console(ctrl, cfg, io, log_on=False).loop()
    text = "\n".join(io.said)
    assert "go to an absolute angle" in text
    assert "unknown command 'bogus'" in text and "'abc' is not a number" in text
    assert "refused:" in text  # g 99 is outside the limits
    assert text.count("now ") >= 3
    logs = list(tmp_path.glob("console-*.jsonl"))
    assert len(logs) == 1
    rows = [json.loads(line) for line in logs[0].read_text().splitlines()]
    assert rows[0]["kind"] == "header" and any(r["kind"] == "step" for r in rows)


def test_console_ends_braked_on_eof(ctrl, hand):
    Console(ctrl, Config(), ScriptedPrompter([]), log_on=False).loop()
    assert (hand.sent[-1][2] >> 4) & 0x7 == 0
