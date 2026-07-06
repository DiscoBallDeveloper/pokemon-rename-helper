from pathlib import Path

def test_legacy_scan_uses_thresholded_league_names():
    text = Path("pogo_auto/legacy_scan.py").read_text(encoding="utf-8")
    assert "build_pvp_rename(rank1, rank2, threshold)" in text
    assert 'parts.append(f"G{compact_pvp_percent(rank1)}")' in text
    assert 'parts.append(f"U{compact_pvp_percent(rank2)}")' in text

def test_legacy_scan_uses_compact_iv_names():
    text = Path("pogo_auto/legacy_scan.py").read_text(encoding="utf-8")
    assert 'parsed["rename_to"] = f"{attack}{defense}{hp}"' in text
