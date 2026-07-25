from pathlib import Path

def test_refresh_patch_uses_existing_wait_variable():
    text = Path("pogo_auto/legacy_scan.py").read_text(encoding="utf-8")
    assert "wait_after_right_retry" in text
    assert "time.sleep(wait_after_right)" in text
