"""Interactive console for one hand: open/close with Enter, go to an angle, status, log toggle, preflight."""
from __future__ import annotations

from .calibrate import auto_zero
from .config import Config
from .i18n import t
from .jsonl_log import JsonlLog, NullLog
from .link import Link, LinkError
from .motion import Controller
from .preflight import PREFLIGHT_STAGES, run_preflight
from .prompter import Prompter

PROMPT = "dex1> "


class Console:
    def __init__(self, ctrl: Controller, cfg: Config, io: Prompter, log_on: bool = True) -> None:
        self.ctrl, self.cfg, self.io = ctrl, cfg, io
        self.ramp_s = cfg.limits.default_ramp_s
        self.q = 0.0
        if log_on:
            self.log_on()

    @property
    def link(self) -> Link:
        return self.ctrl.link

    def log_on(self) -> None:
        if self.link.log.path:
            return
        self.link.log = JsonlLog(self.cfg.log_dir, "console", {"hand": self.cfg.hand.__dict__, "limits": self.cfg.limits.__dict__})
        self.io.say(t("log_path", path=self.link.log.path))

    def log_off(self) -> None:
        if self.link.log.path:
            self.io.say(t("log_closed", path=self.link.log.path))
            self.link.log.close()
            self.link.log = NullLog()

    def move(self, target: float) -> None:
        try:
            result = self.ctrl.move_to(target, self.ramp_s)
        except (ValueError, LinkError) as e:
            self.io.say(t("refused", e=e))
            return
        self.q = result.end_rad
        self.io.say(t("now", q=result.end_rad) + ("" if result.ok else t("stopped", reason=result.reason)))

    def status(self) -> None:
        try:
            r = self.ctrl.read_state()
        except LinkError as e:
            self.io.say(t("no_answer", e=e))
            return
        self.q = r.output_rad
        self.io.say(t("status", q=r.output_rad, c=r.temp_case, k=r.temp_coil, v=r.volts, m=r.merror, r=self.ramp_s,
                      log=t("on") if self.link.log.path else t("off")))

    def auto_zero(self) -> None:
        try:
            result = auto_zero(self.ctrl)
        except LinkError as e:
            self.io.say(t("no_answer", e=e))
            return
        self.io.say(t("zero_done", zero=result.zero_rad, travel=result.travel_rad) + t("zero_look") if result.ok
                    else t("zero_failed", reason=result.reason))

    def handle(self, line: str) -> bool:
        """Run one command line. Returns False to quit."""
        lim = self.cfg.limits
        cmd, _, arg = line.strip().partition(" ")
        try:
            if cmd == "":
                self.status()
                mid = (lim.closed_target_rad + lim.open_target_rad) / 2
                self.move(lim.closed_target_rad if self.q > mid else lim.open_target_rad)
            elif cmd == "o":
                self.move(lim.open_target_rad)
            elif cmd == "c":
                self.move(lim.closed_target_rad)
            elif cmd == "g":
                self.move(float(arg))
            elif cmd == "s":
                self.status()
            elif cmd == "t":
                self.ramp_s = max(lim.check_ramp(float(arg)), lim.min_ramp_s)
                self.io.say(t("ramp_set", s=self.ramp_s))
            elif cmd == "l":
                if arg not in ("on", "off"):
                    self.io.say(t("usage_log"))
                else:
                    self.log_on() if arg == "on" else self.log_off()
            elif cmd == "p":
                stages = run_preflight(self.ctrl, self.io)
                self.io.say(t("pf_ok") if all(s.ok for s in stages) and len(stages) == PREFLIGHT_STAGES else t("pf_ng"))
            elif cmd == "z":
                self.auto_zero()
            elif cmd == "b":
                self.ctrl.brake()
            elif cmd in ("h", "help", "?"):
                self.io.say(t("help"))
            elif cmd == "q":
                return False
            else:
                self.io.say(t("unknown_cmd", cmd=cmd))
        except ValueError:
            self.io.say(t("not_number", arg=arg) if cmd in ("g", "t") else t("bad_value"))
        return True

    def loop(self) -> None:
        self.io.say(t("help_hint"))
        try:
            while self.handle(self.io.ask(PROMPT)):
                pass
        except (EOFError, KeyboardInterrupt):
            self.io.say("")
        finally:
            self.ctrl.brake()
            self.log_off()
