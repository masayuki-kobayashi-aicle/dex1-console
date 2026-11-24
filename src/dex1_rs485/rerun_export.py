"""Turn a JSONL log into a Rerun .rrd (one file = one session). Needs: pip install 'dex1-rs485[rerun]'.

Optionally adds a video you filmed: --video-offset-s is the video time, in seconds, at which the log's t=0 happens.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LABEL_OK = re.compile(r"^[A-Za-z0-9_.|+ -]+$")
# Rerun 0.43+ rewrites an application id that has anything but these (and warns), so the id is made safe here
# and the label itself is shown as the recording name.
APP_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_ -]")


def app_id_for(label: str) -> str:
    return APP_ID_UNSAFE.sub("-", label)


def load_rows(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not any(r.get("kind") == "step" for r in rows):
        raise ValueError(f"{path}: no 'step' rows; is this a dex1-rs485 log of a move?")
    return rows


def export(log: Path, out: Path, label: str, video: Path | None = None, video_offset_s: float = 0.0) -> int:
    """Write out; returns the number of rows logged."""
    if not LABEL_OK.match(label):
        raise ValueError("label may contain only letters, digits, space and _ . | + -")
    try:
        import rerun as rr
        import rerun.blueprint as rrb
    except ImportError as e:
        raise RuntimeError("needs rerun-sdk: pip install 'dex1-rs485[rerun]'") from e
    rows = [r for r in load_rows(log) if "t" in r]
    rr.init(app_id_for(label))
    views = [rrb.TimeSeriesView(origin="position", name="position [rad]"),
             rrb.TimeSeriesView(origin="motor", name="torque / speed / temperature / voltage"),
             rrb.TimeSeriesView(origin="reply", name="reply delay [ms] / missed")]
    layout = rrb.Horizontal(rrb.Spatial2DView(origin="video", name="video"), rrb.Vertical(*views)) if video else rrb.Vertical(*views)
    rr.save(out, default_blueprint=rrb.Blueprint(layout))
    rr.send_recording_name(label)
    if video:
        asset = rr.AssetVideo(path=video)
        rr.log("video", asset, static=True)
        frames = asset.read_frame_timestamps_nanos()
        rr.send_columns("video", indexes=[rr.TimeColumn("t", duration=[n / 1e9 - video_offset_s for n in frames])],
                        columns=rr.VideoFrameReference.columns_nanos(frames))
    for r in rows:
        rr.set_time("t", duration=r["t"])
        if r.get("kind") in ("start", "step", "end", "status", "brake"):
            rr.log("reply/missed", rr.Scalars(0.0 if r.get("rx_len") else 1.0))
        if r.get("rx_len") and "q_out" in r:
            for name, key in (("position/measured", "q_out"), ("motor/torque_raw", "torque_raw"), ("motor/speed_raw", "speed_raw"),
                              ("motor/temp_case_C", "temp_case"), ("motor/temp_coil_C", "temp_coil"), ("motor/volts", "volts"),
                              ("motor/merror", "merror")):
                rr.log(name, rr.Scalars(r[key]))
        if r.get("first_rx_ms") is not None:
            rr.log("reply/first_rx_ms", rr.Scalars(r["first_rx_ms"]))
        if "target" in r:
            rr.log("position/target", rr.Scalars(r["target"]))
        if r.get("kind") == "brake":
            rr.log("event", rr.TextLog("BRAKE"))
    return len(rows)
