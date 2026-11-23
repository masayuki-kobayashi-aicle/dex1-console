from types import SimpleNamespace

import pytest

pytest.importorskip("serial")

from dex1_rs485 import espprog  # noqa: E402


def port(device, location="", vid=0x0403, pid=0x6010):
    return SimpleNamespace(device=device, location=location, vid=vid, pid=pid)


def patch_ports(monkeypatch, ports):
    from serial.tools import list_ports
    monkeypatch.setattr(list_ports, "comports", lambda: ports)


def test_samples_carry_data_and_enable():
    s = espprog.build_samples(b"\xfe")
    assert len(s) == 8 + 1 + 10 + 1 + 8
    assert s[0] == espprog.PIN_TDI and s[8] == espprog.PIN_TDI | espprog.PIN_TMS and s[-1] == espprog.PIN_TDI


def test_single_remaining_port_is_channel_b(monkeypatch):  # Linux: channel A is detached while pyftdi has it
    patch_ports(monkeypatch, [port("/dev/ttyUSB1", "1-2:1.1"), port("/dev/ttyUSB9", vid=1, pid=2)])
    assert espprog.find_channel_b() == "/dev/ttyUSB1"


def test_both_listed_prefers_interface_one(monkeypatch):
    patch_ports(monkeypatch, [port("/dev/cu.usbserial-1420A"), port("/dev/cu.usbserial-1420B")])
    assert espprog.find_channel_b() == "/dev/cu.usbserial-1420B"
    patch_ports(monkeypatch, [port("/dev/ttyUSB0", "1-2:1.0"), port("/dev/ttyUSB1", "1-2:1.1")])
    assert espprog.find_channel_b() == "/dev/ttyUSB1"


def test_no_esp_prog_is_a_clear_error(monkeypatch):
    patch_ports(monkeypatch, [])
    with pytest.raises(RuntimeError, match="no ESP-Prog"):
        espprog.find_channel_b()
