import json

import pytest

from pogo_auto.native_rename import (
    _normalise_display_name,
    apply_native_rename_manifest,
    native_rename_entries,
    native_rename_execution_plan,
    prepare_native_rename_manifest,
)


def _data(path):
    path.write_text(json.dumps({
        "cpm": {"1.0": 0.094, "50.0": 0.84029999},
        "species": [{
            "species": "Examplemon", "form": "NORMAL",
            "base_attack": 120, "base_defense": 140, "base_stamina": 160,
        }],
    }))


def test_prepared_native_rename_manifest_is_verified_only_and_uses_delete2(tmp_path):
    source = tmp_path / "native.json"
    data = tmp_path / "data.json"
    output = tmp_path / "rename.json"
    _data(data)
    source.write_text(json.dumps({"scans": [
        {
            "scan_id": 1, "scan_status": "VERIFIED", "verified_ivs": [13, 13, 13],
            "identity": {"species": "Examplemon", "form": "NORMAL"},
        },
        {
            "scan_id": 2, "scan_status": "VERIFIED", "verified_ivs": [14, 14, 14],
            "identity": {"species": "Examplemon", "form": "NORMAL"},
        },
        {
            "scan_id": 3, "scan_status": "REVIEW", "proposed_ivs": [15, 15, 15],
            "identity": {"species": "Examplemon", "form": "NORMAL"},
        },
    ]}))

    prepare_native_rename_manifest(source, output, data_path=data, pvp_min_percentile=101.0)
    payload = json.loads(output.read_text())
    first, second, review = payload["scans"]
    assert first["rename_decision"] == "DISCARD_TAG"
    assert first["rename_to"] == "delete2"
    assert second["rename_decision"] == "KEEP_RAID"
    assert second["rename_to"] == "141414"
    assert review["rename_allowed"] is False
    assert review["rename_to"] is None
    assert [entry["scan_id"] for entry in native_rename_entries(output)] == [1, 2]
    with pytest.raises(ValueError, match="unsafe scan IDs"):
        native_rename_execution_plan(output)


def test_prepared_native_rename_manifest_allows_custom_discard_tag(tmp_path):
    source = tmp_path / "native.json"
    data = tmp_path / "data.json"
    output = tmp_path / "rename.json"
    _data(data)
    source.write_text(json.dumps({"scans": [{
        "scan_id": 1, "scan_status": "VERIFIED", "verified_ivs": [1, 2, 3],
        "identity": {"species": "Examplemon", "form": "NORMAL"},
    }]}))
    prepare_native_rename_manifest(
        source, output, data_path=data, pvp_min_percentile=101.0, discard_tag="remove2"
    )
    assert json.loads(output.read_text())["scans"][0]["rename_to"] == "remove2"


def test_device_plan_is_reverse_scan_order_and_requires_every_position_verified(tmp_path):
    path = tmp_path / "rename.json"
    path.write_text(json.dumps({"scans": [
        {
            "scan_id": 1, "scan_status": "VERIFIED", "rename_allowed": True,
            "rename_to": "delete2", "verified_ivs": [1, 2, 3],
            "identity": {"species": "One", "form": "NORMAL"},
        },
        {
            "scan_id": 2, "scan_status": "VERIFIED", "rename_allowed": True,
            "rename_to": "141414", "verified_ivs": [14, 14, 14],
            "identity": {"species": "Two", "form": "NORMAL"},
        },
    ]}))
    assert [item["scan_id"] for item in native_rename_execution_plan(path)] == [2, 1]


def test_dry_run_can_resume_at_a_specific_scan(tmp_path):
    path = tmp_path / "rename.json"
    path.write_text(json.dumps({"scans": [
        {
            "scan_id": number, "scan_status": "VERIFIED", "rename_allowed": True,
            "rename_to": "delete2", "verified_ivs": [1, 2, 3],
            "identity": {"species": f"Example{number}", "form": "NORMAL"},
        }
        for number in (1, 2, 3)
    ]}))
    plan = apply_native_rename_manifest(path, adb_serial=None, execute=False, start_scan=2, already_on_detail=True)
    assert [item["scan_id"] for item in plan] == [2, 1]


def test_display_name_normalisation_only_ignores_case_and_whitespace():
    assert _normalise_display_name(" G2032U1642 ") == "g2032u1642"
    assert _normalise_display_name("delete2 ale") != _normalise_display_name("delete2")
