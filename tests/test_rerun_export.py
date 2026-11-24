"""export-rerun: label handling (no rerun needed) and a real export (needs the rerun extra; skipped without it)."""
import pytest

from dex1_rs485.cli import main
from dex1_rs485.rerun_export import app_id_for, export


@pytest.mark.parametrize("label, expected", [
    ("plain label", "plain label"),
    ("ep_01-a b", "ep_01-a b"),
    ("dex1 demo 0.1", "dex1 demo 0-1"),
    ("a|b+c.d", "a-b-c-d"),
])
def test_app_id_keeps_only_characters_rerun_accepts(label, expected):
    assert app_id_for(label) == expected


def test_label_with_other_characters_is_refused(tmp_path):
    log = tmp_path / "x.jsonl"
    log.write_text("{}\n")
    with pytest.raises(ValueError):
        export(log, tmp_path / "o.rrd", "bad/label")


@pytest.mark.parametrize("label", ["plain label", "dex1 demo 0.1"])
def test_export_writes_a_recording_without_rerun_warnings(tmp_path, capfd, label):
    pytest.importorskip("rerun")
    with pytest.raises(SystemExit) as done:  # main() always ends with sys.exit
        main(["--transport", "mock", "--log-dir", str(tmp_path), "cycle", "--cycles", "1", "--ramp-s", "1"])
    assert done.value.code == 0
    log = next(tmp_path.glob("cycle-*.jsonl"))
    out = tmp_path / "out.rrd"
    capfd.readouterr()
    rows = export(log, out, label)
    err = capfd.readouterr().err
    assert rows > 0 and out.stat().st_size > 0
    assert "WARN" not in err, err
