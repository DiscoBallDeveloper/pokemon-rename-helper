from __future__ import annotations

from pathlib import Path

from .native_rename import apply_native_rename_manifest, prepare_native_rename_manifest
from .native_scan import run_native_scan


def run_native_workflow(
    *,
    count: int,
    adb_serial: str | None,
    frames_per_pokemon: int,
    frame_delay_ms: int,
    form: str | None,
    native_manifest_output: str | Path,
    rename_manifest_output: str | Path,
    data_path: str | Path,
    pvp_min_percentile: float,
    min_cap_ratio: float,
    discard_tag: str,
    debug_native: bool,
    execute: bool,
) -> Path | None:
    """Scan forward, then apply a frozen native-only rename plan backward.

    The scan leaves Pokémon GO on the last scanned appraisal.  The renamer
    deliberately consumes the frozen manifest in reverse order, verifying the
    visible native species and IV tuple immediately before each mutation.
    """
    scan_manifest = run_native_scan(
        count=count,
        adb_serial=adb_serial,
        frames_per_pokemon=frames_per_pokemon,
        frame_delay_ms=frame_delay_ms,
        form=form,
        manifest_output=native_manifest_output,
        debug_native=debug_native,
        advance=count > 1,
        open_appraise=True,
        execute=execute,
    )
    if scan_manifest is None:
        print("[DRY RUN] would freeze local ranks and rename in reverse scan order.")
        return None

    rename_manifest = prepare_native_rename_manifest(
        scan_manifest,
        rename_manifest_output,
        data_path=data_path,
        pvp_min_percentile=pvp_min_percentile,
        min_cap_ratio=min_cap_ratio,
        discard_tag=discard_tag,
    )
    # This refuses any REVIEW record, missing rank data, or incomplete
    # identity before the first rename is ever sent to the phone.
    apply_native_rename_manifest(
        rename_manifest,
        adb_serial=adb_serial,
        execute=True,
    )
    return rename_manifest
