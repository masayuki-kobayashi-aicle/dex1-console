"""Command line: dex1 {selftest,probe,console,preflight,move,cycle,gui,export-rerun}. See README.md."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .config import Config, load_config
from .console import Console
from .i18n import set_language, t
from .jsonl_log import JsonlLog, NullLog
from .link import Link, LinkError
from .mock import MockHand
from .motion import Controller
from .preflight import PREFLIGHT_STAGES, run_preflight
from .prompter import TerminalPrompter
from .protocol import build_idle, build_lock, build_position, build_query

SELFTEST_FRAMES = {  # produced by the vendor SDK for motor id 7 (kp 5 -> 102, kd 0.05 -> 1)
    "idle": ("fe ee 17 00 00 00 00 00 00 00 00 00 00 00 00 00 43 4a be 82", lambda: build_idle(7)),
    "position 0.10 rad": ("fe ee 17 00 00 00 00 00 ed 32 00 00 66 00 01 00 ba d3 3d fd", lambda: build_position(7, 0.10)),
    "position 2.00 rad": ("fe ee 17 00 00 00 00 00 97 fa 03 00 66 00 01 00 c9 ed 44 d5", lambda: build_position(7, 2.00)),
    "brake": ("fe ee 07 00 00 00 00 00 00 00 00 00 00 00 00 00 b0 db 8d 63", lambda: build_lock(7)),
}


def selftest() -> int:
    bad = [name for name, (want, make) in SELFTEST_FRAMES.items() if make().hex(" ") != want]
    for name in bad:
        print(f"selftest FAILED: {name}", file=sys.stderr)
    print(t("selftest_ok") if not bad else t("selftest_bad"))
    return 1 if bad else 0


def make_transport(cfg: Config):
    if cfg.transport.kind == "mock":
        return MockHand(cfg.hand.motor_id)
    if cfg.transport.kind == "espprog":
        from .espprog import EspProgTransport
        return EspProgTransport(cfg.transport)
    raise ValueError(f"unknown transport {cfg.transport.kind!r} (espprog or mock)")


def open_controller(cfg: Config, log_prefix: str | None, say=print) -> Controller:
    log = JsonlLog(cfg.log_dir, log_prefix, {"hand": cfg.hand.__dict__, "limits": cfg.limits.__dict__}) if log_prefix else NullLog()
    link = Link(make_transport(cfg), cfg.hand.motor_id, cfg.transport.reply_wait_s, log)
    if log.path:
        say(t("log_path", path=log.path))
    return Controller(link, cfg.hand, cfg.limits, say=say)


def cmd_probe(cfg: Config, args) -> int:
    ctrl = open_controller(cfg, "probe" if args.log else None)
    try:
        r = ctrl.link.txrx(build_query(cfg.hand.motor_id), "probe")
    finally:
        ctrl.link.close()
    if r is None:
        print(t("no_reply", id=cfg.hand.motor_id))
        return 1
    print(f"id={r.motor_id} OK  q={r.output_rad:.3f} rad  temp {r.temp_case}/{r.temp_coil} C  {r.volts:.1f} V  MError {r.merror:#x}  crc {','.join(r.crc_variants)}")
    return 0


def cmd_console(cfg: Config, args) -> int:
    if not sys.stdin.isatty():
        print(t("no_terminal"))
        return 2
    ctrl = open_controller(cfg, None)
    io = TerminalPrompter()
    try:
        if not args.skip_preflight:
            try:
                stages = run_preflight(ctrl, io)
            except EOFError:
                io.say(t("input_closed"))
                return 1
            if len(stages) < 6 or not all(s.ok for s in stages):
                io.say(t("pf_start_failed"))
                return 1
        Console(ctrl, cfg, io, log_on=args.log).loop()
    finally:
        ctrl.link.close()
    return 0


def cmd_preflight(cfg: Config, args) -> int:
    if not sys.stdin.isatty():
        print(t("no_terminal"))
        return 2
    ctrl = open_controller(cfg, "preflight" if args.log else None)
    try:
        stages = run_preflight(ctrl, TerminalPrompter())
    except EOFError:
        print(t("input_closed"))
        return 1
    finally:
        ctrl.brake()
        ctrl.link.close()
    return 0 if len(stages) == PREFLIGHT_STAGES and all(s.ok for s in stages) else 1


def run_moves(cfg: Config, args, targets: list[float], prefix: str) -> int:
    ctrl = open_controller(cfg, prefix if args.log else None)
    code = 0
    try:
        for i, target in enumerate(targets, start=1):
            result = ctrl.move_to(target, args.ramp_s)
            print(f"[{i}/{len(targets)}] {result.start_rad:.3f} -> {result.end_rad:.3f} rad (peak {result.peak_rad:.3f})"
                  + ("" if result.ok else t("stopped", reason=result.reason)))
            if not result.ok:
                code = 1
                break
    except (ValueError, LinkError) as e:
        print(t("refused", e=e), file=sys.stderr)
        code = 2
    finally:
        ctrl.brake()
        ctrl.link.close()
    return code


def cmd_move(cfg: Config, args) -> int:
    return run_moves(cfg, args, [args.to], "move")


def cmd_cycle(cfg: Config, args) -> int:
    lim = cfg.limits
    return run_moves(cfg, args, [lim.open_target_rad, lim.closed_target_rad] * args.cycles, "cycle")


def cmd_gui(cfg: Config, args) -> int:
    from .gui.server import serve
    return serve(cfg, args.port, not args.no_open, args.skip_preflight)


def cmd_export(cfg: Config, args) -> int:
    from .rerun_export import export
    n = export(args.log_file, args.output, args.label, args.video, args.video_offset_s)
    print(t("wrote", out=args.output, n=n))
    return 0


def add_common(p: argparse.ArgumentParser, hidden: bool) -> None:
    """Options valid before and after the subcommand. In the subcommand's parser they have no default, so they never
    overwrite a value given before it."""
    d = {"default": argparse.SUPPRESS} if hidden else {}
    p.add_argument("--config", type=Path, help="TOML settings (see examples/dex1.toml)", **d)
    p.add_argument("--transport", choices=["espprog", "mock"], help="override [transport] kind; mock needs no hardware", **d)
    p.add_argument("--id", type=int, help="motor id (default 7 = right hand in the vendor setup)", **d)
    p.add_argument("--port-b", help="ESP-Prog channel B device, e.g. /dev/ttyUSB1 (default: find it)", **d)
    p.add_argument("--log-dir", help="where JSONL logs go", **d)
    p.add_argument("--lang", choices=["auto", "en", "ja"],
                   help="language of the messages (default: auto from the locale, or [lang] in the config)", **d)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dex1", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    add_common(ap, hidden=False)
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name: str, fn, help_: str, log_default: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        add_common(p, hidden=True)
        p.set_defaults(fn=fn)
        if name != "export-rerun":
            p.add_argument("--no-log", dest="log", action="store_false", help="do not write a JSONL log")
        return p

    st = sub.add_parser("selftest", help="check frame building against the vendor SDK output (no hardware)")
    add_common(st, hidden=True)
    st.set_defaults(fn=None)
    add("probe", cmd_probe, "one state query; exit 0 if the hand answers")
    c = add("console", cmd_console, "interactive console (preflight first)")
    c.add_argument("--skip-preflight", action="store_true")
    add("preflight", cmd_preflight, "connection, state, calibration, motion check")
    m = add("move", cmd_move, "move to an absolute angle and brake")
    m.add_argument("--to", type=float, required=True, help="output-axis angle in rad")
    m.add_argument("--ramp-s", type=float)
    y = add("cycle", cmd_cycle, "open and close N times")
    y.add_argument("--cycles", type=int, default=1)
    y.add_argument("--ramp-s", type=float)
    g = add("gui", cmd_gui, "web GUI on 127.0.0.1: buttons and a live log view")
    g.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default 8765; 0 picks a free one)")
    g.add_argument("--no-open", action="store_true", help="do not open the browser")
    g.add_argument("--skip-preflight", action="store_true", help="allow moves without a passed preflight")
    e = add("export-rerun", cmd_export, "JSONL log -> Rerun .rrd")
    e.add_argument("log_file", type=Path)
    e.add_argument("-o", "--output", type=Path, required=True)
    e.add_argument("--label", required=True)
    e.add_argument("--video", type=Path)
    e.add_argument("--video-offset-s", type=float, default=0.0)
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "selftest":
        set_language(args.lang or "auto")
        sys.exit(selftest())
    try:
        cfg = load_config(args.config)
        set_language(args.lang or cfg.lang)
        if args.transport:
            cfg = replace(cfg, transport=replace(cfg.transport, kind=args.transport))
        if args.id is not None:
            cfg = replace(cfg, hand=replace(cfg.hand, motor_id=args.id))
        if args.port_b:
            cfg = replace(cfg, transport=replace(cfg.transport, port_b=args.port_b))
        if args.log_dir:
            cfg = replace(cfg, log_dir=args.log_dir)
        sys.exit(args.fn(cfg, args))
    except (ValueError, RuntimeError, OSError, LinkError) as e:
        sys.exit(t("error", e=e))
