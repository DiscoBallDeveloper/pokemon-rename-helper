from pathlib import Path

def test_legacy_scan_uses_fixed_navigation():
    text = Path("pogo_auto/legacy_scan.py").read_text(encoding="utf-8")
    assert "tap_fixed_scan_triangle" in text
    assert "Scanner fixed-triangle navigation enabled" in text
