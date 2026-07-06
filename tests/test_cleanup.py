from pathlib import Path
from pogo_auto.cleanup import remove_matching_files

def test_remove_matching_files(tmp_path):
    (tmp_path / "a.png").write_text("x")
    (tmp_path / "b.csv").write_text("x")
    (tmp_path / "keep.txt").write_text("x")

    removed = remove_matching_files(tmp_path, ("*.png", "*.csv"))

    assert removed == 2
    assert not (tmp_path / "a.png").exists()
    assert not (tmp_path / "b.csv").exists()
    assert (tmp_path / "keep.txt").exists()
