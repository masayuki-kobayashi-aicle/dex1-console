import pytest

from dex1_rs485.config import Config
from dex1_rs485.i18n import set_language
from dex1_rs485.jsonl_log import NullLog
from dex1_rs485.link import Link
from dex1_rs485.mock import MockHand
from dex1_rs485.motion import Controller, NoPacer


@pytest.fixture
def cfg() -> Config:
    return Config()


@pytest.fixture
def hand() -> MockHand:
    return MockHand(7)


@pytest.fixture
def ctrl(cfg, hand) -> Controller:
    link = Link(hand, cfg.hand.motor_id, log=NullLog())
    return Controller(link, cfg.hand, cfg.limits, pacer_factory=NoPacer)


@pytest.fixture(autouse=True)
def english():
    set_language("en")
    yield
    set_language("en")
