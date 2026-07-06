from pogo_auto.names import pvp_name_with_markers
from pogo_auto.legacy_scan import pvp_rows_from_raw_text, build_pvp_rename

def test_extract_pvp_rows_with_markers():
    raw = "Deino | IV 82% (14-8-15) | 13.2% ① | 95.4%① | CP 815, lvl 28.0"
    assert pvp_rows_from_raw_text(raw)[:2] == [(13.2, "1"), (95.4, "1")]

def test_marker_name_single_ultra():
    assert build_pvp_rename(13.2, 95.4, 95.0, "1", "1") == "U9541"

def test_marker_name_public_helper():
    assert pvp_name_with_markers(None, 95.4, None, "1") == "U9541"
