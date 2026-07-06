from pogo_auto.legacy_scan import ordered_pvp_percentages_from_raw_text

def test_ordered_pvp_percentages_skips_iv_percent():
    raw = "IV 91% (12-14-15) | 63.7% ① | 99.4% ① | CP 826, lvl 28.0"
    assert ordered_pvp_percentages_from_raw_text(raw)[:2] == [63.7, 99.4]
