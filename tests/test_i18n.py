import pytest

from dex1_rs485.console import Console
from dex1_rs485.config import Config
from dex1_rs485.i18n import CATALOG, resolve, set_language, t
from dex1_rs485.preflight import run_preflight
from dex1_rs485.prompter import ScriptedPrompter


def test_every_key_has_both_languages_and_the_same_placeholders():
    import string

    def fields(text):
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}

    for key, (en, ja) in CATALOG.items():
        assert en and ja, key
        assert fields(en) == fields(ja), key


def test_language_is_resolved_from_the_environment(monkeypatch):
    for var in ("DEX1_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    assert resolve("auto") == "en"
    monkeypatch.setenv("LANG", "ja_JP.UTF-8")
    assert resolve("auto") == "ja"
    monkeypatch.setenv("DEX1_LANG", "en")
    assert resolve("auto") == "en"
    with pytest.raises(ValueError):
        resolve("fr")


def test_preflight_and_console_speak_japanese(ctrl):
    set_language("ja")
    io = ScriptedPrompter(["", "", "h", "bogus", "q"])
    stages = run_preflight(ctrl, io)
    assert all(s.ok for s in stages) and stages[0].name == t("st_env") == "1 環境"
    Console(ctrl, Config(), io, log_on=False).loop()
    text = "\n".join(io.said)
    assert "合格" in text and "絶対位置へ動く" in text and "というコマンドは無い" in text
    assert "PASS" not in text
