"""One hand, driven from the browser. Jobs (connect, preflight, move ...) run on a worker thread, one at a time;
everything that happens is published on the event bus for the log view."""
from __future__ import annotations

import math
import threading
from dataclasses import asdict, replace

from ..cli import make_transport
from ..calibrate import auto_zero
from ..config import Config, HandConfig
from ..i18n import language, set_language, t
from ..jsonl_log import JsonlLog, Log, NullLog
from ..link import Link, LinkError
from ..motion import Controller, Pacer
from ..preflight import PREFLIGHT_STAGES, run_preflight
from ..protocol import MOTOR_ID_MAX, Reply
from .events import EventBus
from .prompts import WebPrompter

MOVES = ("open", "close", "go")  # need a passed preflight
NEEDS_CONNECTION = ("status", "preflight", "zero", "disconnect") + MOVES  # zero needs no preflight: it is how a hand gets calibrated
SHUTDOWN_JOIN_S = 15.0


class BroadcastLog:
    """Wraps the JSONL log: every exchange also goes to the log view."""

    def __init__(self, inner: Log, bus: EventBus, on_reply) -> None:
        self.inner, self.bus, self.on_reply = inner, bus, on_reply

    @property
    def path(self) -> str | None:
        return self.inner.path

    def write(self, kind: str, trace: dict, reply: Reply | None, **extra: object) -> None:
        self.inner.write(kind, trace, reply, **extra)
        row = {"kind": kind, "ok": reply is not None, "first_rx_ms": trace.get("first_rx_ms"), **extra}
        if reply is not None:
            self.on_reply(reply)
            row.update(q=round(reply.output_rad, 4), temp_case=reply.temp_case, temp_coil=reply.temp_coil,
                       volts=round(reply.volts, 2), merror=reply.merror, torque=reply.torque_raw)
        self.bus.publish("row", **row)

    def close(self) -> None:
        self.inner.close()


def _number(params: dict, key: str, required: bool = True) -> float | None:
    value = params.get(key)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(t("not_number", arg=value))
    return float(value)


def _motor_id(params: dict) -> int | None:
    value = params.get("id")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MOTOR_ID_MAX:
        raise ValueError(t("gui_bad_id", value=repr(value)))
    return value


class HandSession:
    def __init__(self, cfg: Config, bus: EventBus, skip_preflight: bool = False, answer_timeout_s: float | None = None,
                 pacer_factory=Pacer, write_log: bool = True) -> None:
        self.cfg, self.bus, self.skip_preflight, self.pacer_factory = cfg, bus, skip_preflight, pacer_factory
        self.write_log = write_log
        self.prompter = WebPrompter(bus) if answer_timeout_s is None else WebPrompter(bus, answer_timeout_s)
        self.ctrl: Controller | None = None
        self.preflight_ok: bool | None = None
        self.telemetry: dict = {}
        self._lock = threading.Lock()
        self._publish_lock = threading.Lock()  # state events are built and published in one step, so their order is the truth
        self._busy: str | None = None
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    # --- state -------------------------------------------------------------------------------------------------
    def state(self) -> dict:
        lim = self.cfg.limits
        with self._lock:
            return {"connected": self.ctrl is not None, "busy": self._busy, "preflight_ok": self.preflight_ok,
                    "skip_preflight": self.skip_preflight, "telemetry": dict(self.telemetry), "lang": language(),
                    "transport": self.cfg.transport.kind, "motor_id": self.cfg.hand.motor_id,
                    "log_path": self.ctrl.link.log.path if self.ctrl else None,
                    "zero_rad": self.ctrl.link.zero_rad if self.ctrl else 0.0,
                    "limits": {k: getattr(lim, k) for k in ("position_min_rad", "open_limit_rad", "closed_target_rad",
                                                            "open_target_rad", "min_ramp_s", "default_ramp_s", "max_ramp_s",
                                                            "min_strength_pct", "max_strength_pct", "max_speed_rad_s")}}

    def _publish_state(self) -> None:
        with self._publish_lock:
            self.bus.publish("state", **self.state())

    def _on_reply(self, reply: Reply) -> None:
        with self._lock:
            self.telemetry = {"q": round(reply.output_rad, 4), "temp_case": reply.temp_case, "temp_coil": reply.temp_coil,
                              "volts": round(reply.volts, 2), "merror": reply.merror, "torque": reply.torque_raw}

    def _say(self, text: str, level: str = "info") -> None:
        self.bus.publish("msg", text=text, level=level)

    # --- entry point from the HTTP layer -----------------------------------------------------------------------
    def do(self, action: str, params: dict) -> tuple[int, dict]:
        """(HTTP status, body). Returns at once; the work runs on the worker thread."""
        if action in ("stop", "brake"):
            return 200, self.stop()
        if action == "lang":
            return self._set_language(params)
        if action not in ("connect", "status", "preflight", "zero", "disconnect") + MOVES:
            return 404, {"error": t("gui_unknown_action", name=action)}
        if action in NEEDS_CONNECTION and self.ctrl is None:
            return 409, {"error": t("gui_not_connected")}
        if action in MOVES and self.preflight_ok is not True and not self.skip_preflight:
            return 409, {"error": t("gui_need_preflight")}
        try:
            job = self._job_for(action, params)
        except ValueError as e:
            return 400, {"error": str(e)}
        return self._start(action, job)

    def _set_language(self, params: dict) -> tuple[int, dict]:
        """Switch the language of the messages built from now on. Needs no job, so it works while the hand moves."""
        lang = params.get("lang")
        if lang not in ("en", "ja"):
            return 400, {"error": t("gui_bad_lang", value=repr(lang))}
        set_language(lang)
        self._publish_state()
        return 200, {"lang": lang}

    def _job_for(self, action: str, params: dict):
        lim = self.cfg.limits
        if action in ("open", "close", "go"):
            target = {"open": lim.open_target_rad, "close": lim.closed_target_rad}.get(action)
            if target is None:
                target = _number(params, "to")
            ramp = _number(params, "ramp_s", required=False)
            strength = _number(params, "strength", required=False)
            speed = _number(params, "speed", required=False)
            if strength is not None:
                lim.check_strength(strength)
            if speed is not None:
                lim.check_speed(speed)
                if ramp is not None:
                    raise ValueError(t("ramp_and_speed"))
            return lambda: self._move(target, ramp, strength, speed)
        if action == "connect":
            motor_id = _motor_id(params)
            return lambda: self._connect(motor_id)
        return {"disconnect": self._disconnect, "status": self._status, "preflight": self._preflight, "zero": self._zero}[action]

    def _start(self, name: str, job) -> tuple[int, dict]:
        with self._lock:
            if self._busy:
                return 409, {"error": t("gui_busy", name=self._busy)}
            self._busy = name
            self._cancel.clear()
        self._publish_state()  # "busy" is announced before the worker can announce "idle"
        self._thread = threading.Thread(target=self._run, args=(job,), name=f"dex1-{name}", daemon=True)
        self._thread.start()
        return 202, {"started": name}

    def _run(self, job) -> None:
        try:
            job()
        except (ValueError, LinkError) as e:
            self._say(t("refused", e=e), "warn")
        except EOFError:
            self._say(t("gui_dialog_closed"), "warn")
        except (RuntimeError, OSError) as e:
            self._say(t("error", e=e), "error")
        finally:
            with self._lock:
                self._busy = None
            self._publish_state()

    def stop(self) -> dict:
        """Interrupts a move (the control loop brakes), refuses open questions, or brakes when idle."""
        self._cancel.set()
        self.prompter.abort()
        self._say(t("gui_stopping"), "warn")
        if self.ctrl is not None and self._busy is None:
            self._start("brake", self._brake)
        return {"stopping": True}

    # --- jobs (worker thread) ----------------------------------------------------------------------------------
    def _connect(self, motor_id: int | None = None) -> None:
        if self.ctrl is not None:
            self._say(t("gui_already"))
            return
        if motor_id is not None:
            self.cfg = replace(self.cfg, hand=replace(self.cfg.hand, motor_id=motor_id))
        if self.cfg.hand.motor_id != HandConfig().motor_id:
            self._say(t("gui_id_note", id=self.cfg.hand.motor_id), "warn")
        header = {"hand": asdict(self.cfg.hand), "limits": asdict(self.cfg.limits)}
        inner = JsonlLog(self.cfg.log_dir, "gui", header) if self.write_log else NullLog()
        log = BroadcastLog(inner, self.bus, self._on_reply)
        try:
            link = Link(make_transport(self.cfg), self.cfg.hand.motor_id, self.cfg.transport.reply_wait_s, log)
        except BaseException:
            log.close()
            raise
        self.ctrl = Controller(link, self.cfg.hand, self.cfg.limits, self.pacer_factory, self._say, self._cancel.is_set)
        self.preflight_ok = None
        if log.path:
            self._say(t("log_path", path=log.path))
        self._say(t("gui_connected", id=self.cfg.hand.motor_id), "ok")

    def _disconnect(self) -> None:
        ctrl, self.ctrl, self.preflight_ok = self.ctrl, None, None
        if ctrl is not None:
            try:
                ctrl.brake()
            finally:
                ctrl.link.close()
        self.telemetry = {}
        self._say(t("gui_disconnected"))

    def _status(self) -> None:
        r = self.ctrl.read_state()
        self._say(t("status", q=r.output_rad, c=r.temp_case, k=r.temp_coil, v=r.volts, m=r.merror,
                    r=self.cfg.limits.default_ramp_s, log=t("on")))

    def _brake(self) -> None:
        self.ctrl.brake()
        self._say(t("gui_braked"), "ok")

    def _preflight(self) -> None:
        try:
            stages = run_preflight(self.ctrl, self.prompter)
        finally:
            self.ctrl.brake()
        self.preflight_ok = len(stages) == PREFLIGHT_STAGES and all(s.ok for s in stages)
        self._say(t("pf_ok") if self.preflight_ok else t("pf_ng"), "ok" if self.preflight_ok else "error")

    def _zero(self) -> None:
        try:
            result = auto_zero(self.ctrl)
        finally:
            self.ctrl.brake()
        if result.ok:
            self.preflight_ok = None  # the angles changed: the preflight has to be run again
            self._say(t("zero_done", zero=result.zero_rad, travel=result.travel_rad), "ok")
            self._say(t("zero_look") + t("zero_rerun_pf"))
        else:
            self._say(t("zero_failed", reason=result.reason), "warn")

    def _move(self, target: float, ramp_s: float | None, strength: float | None = None, speed: float | None = None) -> None:
        kp = None if strength is None else self.ctrl.kp_from_pct(strength)
        result = self.ctrl.move_to(target, ramp_s, kp, speed)
        self._say(t("now", q=result.end_rad) + ("" if result.ok else t("stopped", reason=result.reason)),
                  "info" if result.ok else "error")

    # --- shutdown ----------------------------------------------------------------------------------------------
    def close(self) -> None:
        """Called when the server stops: interrupt, wait for the worker, brake, release the ports."""
        self._cancel.set()
        self.prompter.abort()
        if self._thread is not None:
            self._thread.join(SHUTDOWN_JOIN_S)
        if self.ctrl is not None:
            self._disconnect()
