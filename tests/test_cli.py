from dex1_rs485.cli import main


def run(*argv):
    try:
        main(list(argv))
    except SystemExit as e:
        return e.code
    return 0


def test_selftest():
    assert run("selftest") == 0


def test_probe_and_move_on_the_mock(tmp_path, capsys):
    base = ["--transport", "mock", "--log-dir", str(tmp_path)]
    assert run(*base, "probe") == 0
    assert run(*base, "move", "--to", "1.0", "--ramp-s", "1") == 0
    assert run(*base, "cycle", "--cycles", "1", "--ramp-s", "1") == 0
    assert "OK" in capsys.readouterr().out


def test_move_outside_limits_is_refused(tmp_path):
    assert run("--transport", "mock", "--log-dir", str(tmp_path), "move", "--to", "9") == 2


def test_bad_config_reports_an_error(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[hand]\nnope = 1\n")
    assert "unknown key" in str(run("--config", str(bad), "probe"))


def test_interactive_commands_refuse_without_a_terminal(tmp_path, capsys):
    base = ["--transport", "mock", "--log-dir", str(tmp_path)]
    assert run(*base, "console") == 2 and run(*base, "preflight") == 2
    assert "interactive terminal" in capsys.readouterr().out


def test_common_options_work_before_and_after_the_subcommand(tmp_path, capsys):
    assert run("--lang", "ja", "selftest") == 0
    assert "一致" in capsys.readouterr().out
    assert run("selftest", "--lang", "ja") == 0
    assert "一致" in capsys.readouterr().out
    assert run("--lang", "ja", "--transport", "mock", "--log-dir", str(tmp_path), "move", "--to", "9") == 2
    assert run("move", "--to", "9", "--lang", "ja", "--transport", "mock", "--log-dir", str(tmp_path)) == 2
    assert "範囲" in capsys.readouterr().err


def test_gui_passes_no_log_to_the_server(monkeypatch, tmp_path):
    seen = {}

    def fake_serve(cfg, port, open_browser, skip_preflight, write_log=True):
        seen["write_log"] = write_log
        return 0

    monkeypatch.setattr("dex1_rs485.gui.server.serve", fake_serve)
    base = ["--transport", "mock", "--log-dir", str(tmp_path), "gui", "--no-open"]
    assert run(*base) == 0 and seen["write_log"] is True
    assert run(*base, "--no-log") == 0 and seen["write_log"] is False
