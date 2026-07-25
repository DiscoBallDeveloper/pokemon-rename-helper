from pathlib import Path

def test_legacy_scan_uses_swipe_navigation():
    text = Path("pogo_auto/legacy_scan.py").read_text(encoding="utf-8")
    assert "swipe_fixed_scan_triangle_level" in text
    assert "Scanner swipe navigation enabled" in text
