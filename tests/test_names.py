from pogo_auto.names import pvp_name, iv_name, classify_for_name

def test_pvp_name_combines():
    assert pvp_name(97.2, 95.9) == "G972U959"

def test_iv_name():
    assert iv_name(14, 15, 15) == "141515"

def test_classify_pvp_keep():
    d = classify_for_name(None, None, None, 97.2, 80.5)
    assert d.decision == "KEEP"
    assert d.rename_to == "G972"
