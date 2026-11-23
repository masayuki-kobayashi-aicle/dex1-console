"""The web GUI against the mock hand: real HTTP on a free port, no browser."""
import json
import struct
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace

import pytest

from dex1_rs485.config import Config, TransportConfig
from dex1_rs485.gui.events import EventBus
from dex1_rs485.gui.server import GuiServer
from dex1_rs485.gui.session import HandSession
from dex1_rs485.motion import NoPacer, Pacer


@pytest.fixture
def gui(tmp_path):
    cfg = replace(Config(), transport=TransportConfig(kind="mock"), log_dir=str(tmp_path))
    bus = EventBus()
    session = HandSession(cfg, bus, pacer_factory=NoPacer)
    server = GuiServer(0, session, bus)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.closing.set()
    session.close()
    server.shutdown()
    server.server_close()


def call(server, action, body=None, token=True, host=None, origin=None, ctype="application/json"):
    headers = {"Content-Type": ctype, "Host": host or f"127.0.0.1:{server.server_port}"}
    if token:
        headers["X-Dex1-Token"] = server.token
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(f"{server.url}api/{action}", json.dumps(body or {}).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait_idle(server, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if server.session.state()["busy"] is None:
            return
        time.sleep(0.02)
    raise AssertionError("session stayed busy")


def texts(server):
    return [e.get("text", "") for e in server.bus._history if e["type"] == "msg"]


def test_page_embeds_the_token_and_language(gui):
    with urllib.request.urlopen(gui.url) as r:
        body = r.read().decode()
        assert r.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert gui.token in body and "__TOKEN__" not in body and "__LANG__" not in body


@pytest.mark.parametrize("kwargs", [{"token": False}, {"host": "evil.example"}, {"origin": "http://evil.example"}])
def test_requests_without_token_or_from_elsewhere_are_refused(gui, kwargs):
    status, _ = call(gui, "connect", **kwargs)
    assert status == 403
    assert gui.session.state()["connected"] is False


def test_non_json_content_type_is_refused(gui):
    assert call(gui, "connect", ctype="text/plain")[0] == 415


def test_event_stream_needs_the_token(gui):
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(f"{gui.url}events?token=wrong")
    assert err.value.code == 403


def test_moves_need_a_connection_and_a_passed_preflight(gui):
    assert call(gui, "open")[0] == 409
    assert call(gui, "connect")[0] == 202
    wait_idle(gui)
    status, body = call(gui, "open")
    assert status == 409 and "preflight" in body["error"]
    assert all((f[2] >> 4) & 7 == 0 for f in gui.session.ctrl.link.transport.sent)  # no torque frame was sent


def run_preflight(gui):
    assert call(gui, "connect")[0] == 202
    wait_idle(gui)
    assert call(gui, "preflight")[0] == 202
    ask = wait_for(gui, "ask", ["yes", "no"])
    assert call(gui, "answer", {"qid": ask["qid"], "value": "yes"})[0] == 200
    wait_idle(gui)


def wait_for(gui, kind, choices, timeout=20.0):
    end = time.monotonic() + timeout
    seen = {e["qid"] for e in gui.bus._history if e["type"] == "ask_done"}
    while time.monotonic() < end:
        for e in gui.bus._history:
            if e["type"] == kind and e["qid"] not in seen and e["choices"] == choices:
                return e
        time.sleep(0.02)
    raise AssertionError(f"no {kind} with {choices}")


def test_preflight_then_open_and_close(gui):
    run_preflight(gui)
    state = gui.session.state()
    assert state["preflight_ok"] is True
    assert call(gui, "open")[0] == 202
    wait_idle(gui)
    assert gui.session.state()["telemetry"]["q"] > 4.0
    assert call(gui, "close")[0] == 202
    wait_idle(gui)
    assert gui.session.state()["telemetry"]["q"] < 1.0
    assert any(e["type"] == "row" for e in gui.bus._history)


def test_the_preflight_asks_one_question_a_visual_check(gui):
    assert call(gui, "connect")[0] == 202
    wait_idle(gui)
    call(gui, "preflight")
    look = wait_for(gui, "ask", ["yes", "no"])
    call(gui, "answer", {"qid": look["qid"], "value": "yes"})
    wait_idle(gui)
    assert gui.session.state()["preflight_ok"] is True
    assert [e for e in gui.bus._history if e["type"] == "ask"] == [look]


def test_saying_the_hand_is_not_closed_fails_the_preflight(gui):
    assert call(gui, "connect")[0] == 202
    wait_idle(gui)
    call(gui, "preflight")
    look = wait_for(gui, "ask", ["yes", "no"])
    call(gui, "answer", {"qid": look["qid"], "value": "no"})
    wait_idle(gui)
    assert gui.session.state()["preflight_ok"] is False
    assert call(gui, "open")[0] == 409


def test_bad_parameters_are_rejected_not_sent(gui):
    run_preflight(gui)
    sent_before = len(gui.session.ctrl.link.transport.sent)
    assert call(gui, "go", {"to": "abc"})[0] == 400
    assert call(gui, "go", {"to": float("nan")})[0] == 400
    assert call(gui, "go", {"to": 99.0})[0] == 202  # out of range: the controller refuses it, nothing is sent
    wait_idle(gui)
    assert any("outside" in x for x in texts(gui))
    assert call(gui, "go", {"to": 2.0, "ramp_s": float("inf")})[0] == 400
    assert len(gui.session.ctrl.link.transport.sent) == sent_before  # refused moves send nothing


def test_stop_interrupts_a_move_and_brakes(gui):
    run_preflight(gui)
    gui.session.ctrl._pacer_factory = Pacer  # real timing, so the move lasts long enough to interrupt
    assert call(gui, "open", {"ramp_s": 10.0})[0] == 202
    time.sleep(0.6)
    assert call(gui, "stop")[0] == 200
    wait_idle(gui)
    assert any("interrupted" in x for x in texts(gui))
    sent = gui.session.ctrl.link.transport.sent
    assert any((f[2] >> 4) & 7 == 1 for f in sent)  # it did start moving
    assert (sent[-2][2] >> 4) & 7 == 0  # brakes, then the end-of-move read


def test_second_job_while_busy_is_refused(gui):
    run_preflight(gui)
    gui.session.ctrl._pacer_factory = Pacer
    call(gui, "open", {"ramp_s": 10.0})
    time.sleep(0.3)
    status, body = call(gui, "close")
    assert status == 409 and "busy" in body["error"]
    call(gui, "stop")
    wait_idle(gui)


def test_disconnect_releases_the_hand(gui):
    run_preflight(gui)
    hand = gui.session.ctrl.link.transport
    assert call(gui, "disconnect")[0] == 202
    wait_idle(gui)
    assert hand.closed and gui.session.state()["connected"] is False


def test_answering_nothing_times_out_without_moving(tmp_path):
    cfg = replace(Config(), transport=TransportConfig(kind="mock"), log_dir=str(tmp_path))
    session = HandSession(cfg, EventBus(), answer_timeout_s=0.2)
    session.do("connect", {})
    session._thread.join(5)
    session.do("preflight", {})
    session._thread.join(5)
    assert session.preflight_ok is None
    assert any("without an answer" in e.get("text", "") for e in session.bus._history)
    session.close()


def test_every_job_announces_busy_then_idle_in_order(gui):
    """Quick jobs (a refused move) used to finish before 'busy' was announced, leaving a stale 'busy' as the last state."""
    run_preflight(gui)
    for _ in range(30):
        assert call(gui, "go", {"to": 99.0})[0] == 202
        wait_idle(gui)
    states = [e["busy"] for e in gui.bus._history if e["type"] == "state"]
    assert states[-1] is None
    tail = states[-60:]
    assert all((a is None) != (b is None) for a, b in zip(tail, tail[1:]))  # strictly alternating busy / idle


def test_language_switch_changes_later_messages_and_is_announced(gui):
    assert call(gui, "lang", {"lang": "ja"}) == (200, {"lang": "ja"})
    assert gui.session.state()["lang"] == "ja"
    assert [e for e in gui.bus._history if e["type"] == "state"][-1]["lang"] == "ja"
    assert call(gui, "connect")[0] == 202
    wait_idle(gui)
    assert any("接続した" in x for x in texts(gui))
    assert call(gui, "lang", {"lang": "en"})[0] == 200
    assert call(gui, "disconnect")[0] == 202
    wait_idle(gui)
    assert any("disconnected" in x for x in texts(gui))


@pytest.mark.parametrize("body", [{}, {"lang": "fr"}, {"lang": "auto"}, {"lang": 1}, {"lang": None}])
def test_language_switch_rejects_anything_but_en_and_ja(gui, body):
    status, reply = call(gui, "lang", body)
    assert status == 400 and reply["error"]
    assert gui.session.state()["lang"] == "en"


def test_language_switch_needs_the_token_and_the_page_offers_both(gui):
    assert call(gui, "lang", {"lang": "ja"}, token=False)[0] == 403
    assert gui.session.state()["lang"] == "en"
    page = urllib.request.urlopen(gui.url).read().decode()
    assert 'data-lang="en"' in page and 'data-lang="ja"' in page


def test_language_can_be_switched_while_a_move_runs(gui):
    gui.session.pacer_factory = Pacer
    call(gui, "connect")
    wait_idle(gui)
    gui.session.preflight_ok = True
    assert call(gui, "open", {"ramp_s": 20})[0] == 202
    assert call(gui, "lang", {"lang": "ja"})[0] == 200
    assert call(gui, "stop")[0] == 200
    wait_idle(gui)


def test_connect_uses_the_chosen_motor_id_and_warns_when_it_is_not_7(gui):
    assert call(gui, "connect", {"id": 3})[0] == 202
    wait_idle(gui)
    state = gui.session.state()
    assert state["connected"] and state["motor_id"] == 3
    assert any("id 3" in x and "only" in x for x in texts(gui))


@pytest.mark.parametrize("bad", [16, -1, "7", 7.5, True, []])
def test_connect_rejects_a_bad_motor_id_and_connects_nothing(gui, bad):
    status, reply = call(gui, "connect", {"id": bad})
    assert status == 400 and reply["error"]
    assert gui.session.state()["connected"] is False


def test_strength_sets_the_gain_of_the_move_and_is_limited(gui):
    run_preflight(gui)
    assert call(gui, "go", {"to": 2.0, "strength": 50})[0] == 202
    wait_idle(gui)
    sent = gui.session.ctrl.link.transport.sent
    gains = {struct.unpack("<H", f[12:14])[0] for f in sent[-80:] if (f[2] >> 4) & 7 == 1 and struct.unpack("<H", f[12:14])[0]}
    assert gains == {51}
    for bad in (5, 150, "x", True):
        assert call(gui, "go", {"to": 2.0, "strength": bad})[0] == 400


def test_auto_zero_asks_nothing_and_then_needs_a_new_preflight(gui):
    run_preflight(gui)
    assert gui.session.state()["preflight_ok"] is True
    asks_before = len([e for e in gui.bus._history if e["type"] == "ask"])
    assert call(gui, "zero")[0] == 202
    wait_idle(gui)
    assert len([e for e in gui.bus._history if e["type"] == "ask"]) == asks_before  # no dialog
    state = gui.session.state()
    assert state["zero_rad"] == pytest.approx(-0.06, abs=0.02)
    assert state["preflight_ok"] is None and abs(state["telemetry"]["q"]) < 0.02
    assert any("auto zero done" in x for x in texts(gui)) and any("by eye" in x for x in texts(gui))
    assert call(gui, "open")[0] == 409  # moves wait for the preflight again


def test_auto_zero_works_before_the_preflight(gui):
    assert call(gui, "zero")[0] == 409  # not connected
    assert call(gui, "connect")[0] == 202
    wait_idle(gui)
    assert call(gui, "zero")[0] == 202
    wait_idle(gui)
    assert gui.session.state()["zero_rad"] != 0.0


def test_telemetry_and_rows_carry_the_torque_reading(gui):
    assert call(gui, "connect")[0] == 202
    wait_idle(gui)
    assert call(gui, "status")[0] == 202
    wait_idle(gui)
    assert "torque" in gui.session.state()["telemetry"]
    assert any(e["type"] == "row" and "torque" in e for e in gui.bus._history)


@pytest.mark.parametrize("write_log", [True, False])
def test_write_log_flag_controls_the_jsonl_file(tmp_path, write_log):
    cfg = replace(Config(), transport=TransportConfig(kind="mock"), log_dir=str(tmp_path))
    session = HandSession(cfg, EventBus(), write_log=write_log)
    session.do("connect", {})
    session._thread.join(5)
    assert session.state()["connected"] is True
    assert bool(session.state()["log_path"]) is write_log
    assert len(list(tmp_path.glob("*.jsonl"))) == (1 if write_log else 0)
    assert any(e.get("text", "").startswith(("log:", "ログ:")) for e in session.bus._history) is write_log
    session.close()
