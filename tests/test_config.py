import pytest

from dex1_rs485.config import Limits, load_config


def test_defaults_and_toml_override(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('log_dir = "/x"\n[hand]\nmotor_id = 3\n[limits]\nopen_limit_rad = 4.0\nopen_target_rad = 3.9\n')
    cfg = load_config(f)
    assert cfg.hand.motor_id == 3 and cfg.limits.open_limit_rad == 4.0 and cfg.log_dir == "/x"
    assert cfg.transport.baud == 6_000_000
    assert load_config(None).hand.motor_id == 7


@pytest.mark.parametrize("text", ["[hand]\nmotor = 3\n", "[nope]\nx = 1\n", "unknown = 1\n"])
def test_unknown_keys_are_rejected(tmp_path, text):
    f = tmp_path / "c.toml"
    f.write_text(text)
    with pytest.raises(ValueError):
        load_config(f)


def test_inconsistent_limits_are_rejected():
    with pytest.raises(ValueError):
        Limits(open_limit_rad=0.0)
    with pytest.raises(ValueError):
        Limits(step_s=0)


def test_the_example_config_loads_and_matches_the_defaults():
    from pathlib import Path

    from dex1_rs485.config import Config

    cfg = load_config(Path(__file__).parents[1] / "examples" / "dex1.toml")
    assert cfg == Config()
