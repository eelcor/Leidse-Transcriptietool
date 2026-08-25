"""STT-hotword-selectie: eigennamen/afkortingen vooraan, generiek jargon achteraan, tot een limiet."""
from worker.worker import _select_hotwords


def test_names_and_acronyms_come_first():
    g = "\n".join([
        "mantelzorg", "LUMC", "omgevingsvisie", "Leidse Ring Noord",
        "bijstand", "GGD", "Henri Lenferink",
    ])
    hw = _select_hotwords(g, 200)
    # afkortingen en (meerwoordige) eigennamen vooraan
    assert hw.find("LUMC") >= 0 and hw.find("Henri Lenferink") >= 0
    # generiek kleingeschreven jargon staat achteraan of valt buiten de limiet
    assert hw.find("mantelzorg") == -1 or hw.find("mantelzorg") > hw.find("LUMC")


def test_respects_limit():
    hw = _select_hotwords("\n".join(["Naam%02d" % i for i in range(100)]), 60)
    assert hw is not None and len(hw) <= 60


def test_empty_and_dedup():
    assert _select_hotwords(None) is None
    assert _select_hotwords("   ") is None
    hw = _select_hotwords("APV\napv\nAPV\n", 200)          # hoofdletterongevoelig ontdubbeld
    assert hw.lower().count("apv") == 1
