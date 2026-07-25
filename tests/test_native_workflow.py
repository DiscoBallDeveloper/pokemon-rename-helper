from pathlib import Path

import pogo_auto.native_workflow as workflow


def _kwargs(execute: bool):
    return dict(
        count=2,
        adb_serial="serial",
        frames_per_pokemon=3,
        frame_delay_ms=350,
        form="NORMAL",
        native_manifest_output="native.json",
        rename_manifest_output="rename.json",
        data_path="data.json",
        pvp_min_percentile=95.0,
        min_cap_ratio=0.90,
        discard_tag="delete2",
        debug_native=True,
        execute=execute,
    )


def test_native_workflow_dry_run_does_not_prepare_or_rename(monkeypatch):
    calls = []

    def scan(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(workflow, "run_native_scan", scan)
    assert workflow.run_native_workflow(**_kwargs(False)) is None
    assert calls == [{
        "count": 2,
        "adb_serial": "serial",
        "frames_per_pokemon": 3,
        "frame_delay_ms": 350,
        "form": "NORMAL",
        "manifest_output": "native.json",
        "advance": True,
        "open_appraise": True,
        "debug_native": True,
        "execute": False,
    }]


def test_native_workflow_freezes_then_applies_reverse_manifest(monkeypatch):
    calls = []

    monkeypatch.setattr(workflow, "run_native_scan", lambda **kwargs: Path("native.json"))
    monkeypatch.setattr(
        workflow,
        "prepare_native_rename_manifest",
        lambda *args, **kwargs: calls.append(("prepare", args, kwargs)) or Path("rename.json"),
    )
    monkeypatch.setattr(
        workflow,
        "apply_native_rename_manifest",
        lambda *args, **kwargs: calls.append(("apply", args, kwargs)),
    )
    assert workflow.run_native_workflow(**_kwargs(True)) == Path("rename.json")
    assert calls[0][0] == "prepare"
    assert calls[1] == ("apply", (Path("rename.json"),), {"adb_serial": "serial", "execute": True})
