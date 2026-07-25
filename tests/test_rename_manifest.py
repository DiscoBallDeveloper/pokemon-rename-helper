import json

from pogo_auto.rename_manifest import verified_entries


def test_manifest_filters_review_entries(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"scans": [
        {"scan_status": "REVIEW", "rename_allowed": True, "ivs": [1, 2, 3], "identity": {"species": "Wooloo", "form": "NORMAL"}},
        {"scan_status": "VERIFIED", "rename_allowed": True, "ivs": [1, 2, 3], "identity": {"species": "Wooloo", "form": "NORMAL"}},
    ]}))
    assert len(verified_entries(path)) == 1
