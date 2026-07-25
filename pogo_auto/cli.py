from __future__ import annotations

import argparse
from pathlib import Path

from .cleanup import clean_runtime_outputs
from .adb import CONNECT_PORT, AdbTarget, connect_wifi, kill_pokegenie, list_devices, pair_wifi, require_device
from .settings import AppConfig
from .workflow import run_rename, run_scan, run_workflow
from .doctor import run_doctor
from .native_scan import run_native_scan
from .rename_manifest import verified_entries
from .rank_data import convert_pokeminers_game_master
from .pvp_rank import PokemonData, all_league_ranks, evolution_league_ranks
from .pvp_naming import suggested_pvp_name
from .native_rename import (
    apply_native_rename_manifest,
    native_rename_entries,
    prepare_native_rename_manifest,
)
from .native_workflow import run_native_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pogo",
        description="Pokémon GO + Poke Genie local ADB/OCR scan and rename workflow.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("devices", help="Show ADB devices.")
    p.set_defaults(func=cmd_devices)

    p = sub.add_parser("clean", help="Remove old screenshots, crops, and logs. Templates are kept.")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("doctor", help="Check ADB, Python dependencies, connected device, and templates.")
    p.add_argument("--no-device", action="store_true", help="Skip checking for a connected ADB device.")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("wifi-pair", help="Pair Android 11+ wireless debugging using a pairing IP:port.")
    p.add_argument("host")
    p.add_argument("--port", type=int, required=True)
    p.set_defaults(func=cmd_wifi_pair)

    p = sub.add_parser("wifi-connect", help="Connect to an already paired Wi-Fi ADB target.")
    p.add_argument("host")
    p.add_argument("--port", type=int, default=CONNECT_PORT)
    p.set_defaults(func=cmd_wifi_connect)

    p = sub.add_parser("kill-pokegenie", help="Force-stop Poke Genie and return to Pokémon GO.")
    add_device_arg(p)
    p.set_defaults(func=cmd_kill)

    p = sub.add_parser("scan", help="Run scan pass only.")
    add_common_run_args(p)
    p.add_argument("--wait-before-ocr", type=float, default=3.0)
    p.add_argument("--wait-after-next", type=float, default=3.0)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("native-scan", help="Capture native appraisal evidence and write a review-first manifest.")
    add_common_run_args(p)
    p.add_argument("--frames-per-pokemon", type=int, default=3)
    p.add_argument("--frame-delay-ms", type=int, default=350)
    p.add_argument("--form", default=None, help="Explicit Pokémon form, e.g. NORMAL. Required for VERIFIED.")
    p.add_argument("--manifest-output", default="captures/logs/native_manifest.json")
    p.add_argument("--debug-native", action="store_true", help="Write per-frame native detector debug images.")
    p.add_argument("--advance", action="store_true", help="Intentionally swipe to the next Pokémon between scans.")
    p.add_argument("--already-appraising", action="store_true", help="Do not open the three-bar menu and Appraise panel first.")
    p.set_defaults(func=cmd_native_scan)

    p = sub.add_parser(
        "native-workflow",
        help="Scan forward with native appraisal, then safely rename backward from a frozen local-rank manifest.",
    )
    add_device_arg(p)
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--frames-per-pokemon", type=int, default=3)
    p.add_argument("--frame-delay-ms", type=int, default=350)
    p.add_argument("--form", default=None, help="Explicit Pokémon form, e.g. NORMAL. Required for VERIFIED.")
    p.add_argument("--data", default="captures/data/pokemon_stats_and_cpm.json")
    p.add_argument("--native-manifest-output", default="captures/logs/native_manifest.json")
    p.add_argument("--rename-manifest-output", default="captures/logs/native_rename_manifest.json")
    p.add_argument("--pvp-min-percentile", type=float, default=95.0)
    p.add_argument("--min-cap-ratio", type=float, default=0.90)
    p.add_argument("--discard-tag", default="delete2")
    p.add_argument("--debug-native", action="store_true")
    p.add_argument("--execute", action="store_true", help="Actually scan and rename; otherwise print a non-mutating plan.")
    p.set_defaults(func=cmd_native_workflow)

    p = sub.add_parser("manifest-status", help="Show how many manifest entries are safe candidates for future rename.")
    p.add_argument("manifest")
    p.set_defaults(func=cmd_manifest_status)

    p = sub.add_parser(
        "prepare-native-renames",
        help="Freeze verified native scans into an evolution-aware rename manifest.",
    )
    p.add_argument("manifest", help="Native evidence manifest produced by pogo native-scan.")
    p.add_argument("--output", default="captures/logs/native_rename_manifest.json")
    p.add_argument("--data", default="captures/data/pokemon_stats_and_cpm.json")
    p.add_argument("--pvp-min-percentile", type=float, default=95.0)
    p.add_argument("--min-cap-ratio", type=float, default=0.90)
    p.add_argument("--discard-tag", default="delete2", help="Tag for verified non-keepers (default: delete2).")
    p.set_defaults(func=cmd_prepare_native_renames)

    p = sub.add_parser(
        "native-rename",
        help="Apply a frozen verified-native rename manifest, starting on its last scanned appraisal.",
    )
    p.add_argument("manifest", help="Manifest produced by prepare-native-renames.")
    add_device_arg(p)
    p.add_argument("--execute", action="store_true", help="Actually rename; without it, print the checked action plan only.")
    p.add_argument("--wait-after-pencil", type=float, default=1.0)
    p.add_argument("--wait-after-confirm", type=float, default=1.0)
    p.add_argument("--start-scan", type=int, default=None, help="Resume at this scan ID, processing it down to scan 1.")
    p.add_argument("--already-on-detail", action="store_true", help="For --start-scan recovery: current Pokémon is already on its normal detail page, not Appraise.")
    p.set_defaults(func=cmd_native_rename)

    p = sub.add_parser("build-rank-data", help="Convert a PokeMiners Game Master JSON into validated local rank data.")
    p.add_argument("game_master", help="Downloaded PokeMiners latest.json")
    p.add_argument("--output", default="captures/data/pokemon_stats_and_cpm.json")
    p.add_argument("--max-level", type=int, default=50)
    p.set_defaults(func=cmd_build_rank_data)

    p = sub.add_parser("rank", help="Calculate GL/UL/ML IV-spread ranks from local verified IVs.")
    p.add_argument("species")
    p.add_argument("attack", type=int)
    p.add_argument("defense", type=int)
    p.add_argument("hp", type=int)
    p.add_argument("--data", default="captures/data/pokemon_stats_and_cpm.json")
    p.add_argument("--form", default="NORMAL")
    p.add_argument("--max-level", type=float, default=50.0)
    p.add_argument("--evolutions", action="store_true", help="Also rank evolutions that can approach a league cap.")
    p.add_argument("--min-cap-ratio", type=float, default=0.90, help="Minimum evolved CP/cap ratio to report (default: 0.90).")
    p.add_argument("--suggest-name", action="store_true", help="Print the compact <=12-character GL/UL evolution-aware name.")
    p.set_defaults(func=cmd_rank)

    p = sub.add_parser("rename", help="Run rename pass only.")
    add_common_run_args(p)
    add_rename_timing_args(p)
    p.set_defaults(func=cmd_rename)

    p = sub.add_parser("workflow", help="Run scan; rename is disabled unless explicitly requested.")
    add_common_run_args(p)
    p.add_argument("--no-clean-start", action="store_true", help="Do not remove old screenshots/logs before starting.")
    p.add_argument("--rename-after-scan", action="store_true", help="Run legacy rename after scan (unsafe without a verified native manifest).")
    p.add_argument("--no-rename", action="store_true", help="Explicitly keep the workflow scan-only (the safe default).")
    p.add_argument("--config", default=None, help="Optional JSON config file.")
    p.add_argument("--wait-before-ocr", type=float, default=3.0)
    p.add_argument("--wait-after-next", type=float, default=3.0)
    add_rename_timing_args(p)
    p.set_defaults(func=cmd_workflow)

    p = sub.add_parser("init-config", help="Write a config JSON template.")
    p.add_argument("--output", default="config.json")
    p.set_defaults(func=cmd_init_config)

    return parser


def add_device_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--adb-serial",
        default=None,
        help="USB serial or Wi-Fi serial, e.g. USB_SERIAL or PHONE_IP:CONNECT_PORT",
    )


def add_common_run_args(parser: argparse.ArgumentParser) -> None:
    add_device_arg(parser)
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Run without --execute.")


def add_rename_timing_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--wait-after-pencil", type=float, default=1.5)
    parser.add_argument("--wait-after-appraise-before-triangle-reveal", type=float, default=1.5)
    parser.add_argument("--wait-after-triangle-reveal", type=float, default=2.0)


def cmd_clean(args: argparse.Namespace) -> None:
    removed = clean_runtime_outputs()
    print(f"Removed {removed} old screenshot/crop/log file(s).")


def cmd_devices(args: argparse.Namespace) -> None:
    devices = list_devices()
    if not devices:
        print("No ADB devices found.")
        return
    for device in devices:
        print(device)


def cmd_wifi_pair(args: argparse.Namespace) -> None:
    pair_wifi(args.host, args.port)


def cmd_wifi_connect(args: argparse.Namespace) -> None:
    connect_wifi(args.host, args.port)
    cmd_devices(args)


def cmd_kill(args: argparse.Namespace) -> None:
    serial = require_device(args.adb_serial)
    kill_pokegenie(AdbTarget(serial=serial))


def cmd_scan(args: argparse.Namespace) -> None:
    count = args.count if args.count is not None else 5
    run_scan(
        count=count,
        adb_serial=args.adb_serial,
        wait_before_ocr=args.wait_before_ocr,
        wait_after_next=args.wait_after_next,
        execute=not args.dry_run,
    )


def cmd_native_scan(args: argparse.Namespace) -> None:
    count = args.count if args.count is not None else 1
    run_native_scan(
        count=count,
        adb_serial=args.adb_serial,
        frames_per_pokemon=args.frames_per_pokemon,
        frame_delay_ms=args.frame_delay_ms,
        form=args.form,
        manifest_output=args.manifest_output,
        debug_native=args.debug_native,
        advance=args.advance,
        open_appraise=not args.already_appraising,
        execute=not args.dry_run,
    )


def cmd_native_workflow(args: argparse.Namespace) -> None:
    if args.count < 1:
        raise SystemExit("--count must be positive")
    if not 0.0 <= args.pvp_min_percentile <= 100.0:
        raise SystemExit("--pvp-min-percentile must be between 0 and 100")
    if not 0.0 < args.min_cap_ratio <= 1.0:
        raise SystemExit("--min-cap-ratio must be in (0, 1]")
    output = run_native_workflow(
        count=args.count,
        adb_serial=args.adb_serial,
        frames_per_pokemon=args.frames_per_pokemon,
        frame_delay_ms=args.frame_delay_ms,
        form=args.form,
        native_manifest_output=args.native_manifest_output,
        rename_manifest_output=args.rename_manifest_output,
        data_path=args.data,
        pvp_min_percentile=args.pvp_min_percentile,
        min_cap_ratio=args.min_cap_ratio,
        discard_tag=args.discard_tag,
        debug_native=args.debug_native,
        execute=args.execute,
    )
    if output:
        print(f"Native scan-and-rename workflow completed: {output}")


def cmd_manifest_status(args: argparse.Namespace) -> None:
    entries = verified_entries(args.manifest)
    print(f"Verified rename candidates: {len(entries)}")
    for entry in entries:
        print(f"scan {entry.get('scan_id')}: {entry['identity']['species']} {entry['ivs']}")


def cmd_prepare_native_renames(args: argparse.Namespace) -> None:
    if not 0.0 <= args.pvp_min_percentile <= 100.0:
        raise SystemExit("--pvp-min-percentile must be between 0 and 100")
    if not 0.0 < args.min_cap_ratio <= 1.0:
        raise SystemExit("--min-cap-ratio must be in (0, 1]")
    output = prepare_native_rename_manifest(
        args.manifest,
        args.output,
        data_path=args.data,
        pvp_min_percentile=args.pvp_min_percentile,
        min_cap_ratio=args.min_cap_ratio,
        discard_tag=args.discard_tag,
    )
    entries = native_rename_entries(output)
    decisions: dict[str, int] = {}
    for entry in entries:
        decision = str(entry.get("rename_decision", "UNKNOWN"))
        decisions[decision] = decisions.get(decision, 0) + 1
        print(
            f"scan {entry.get('scan_id')}: {entry['identity']['species']} "
            f"{entry.get('verified_ivs')} -> {entry['rename_to']} ({decision})"
        )
    summary = ", ".join(f"{name}={count}" for name, count in sorted(decisions.items())) or "none"
    print(f"Prepared {len(entries)} verified rename action(s): {summary}")
    print(f"Frozen native rename manifest written: {output}")


def cmd_native_rename(args: argparse.Namespace) -> None:
    apply_native_rename_manifest(
        args.manifest,
        adb_serial=args.adb_serial,
        execute=args.execute,
        wait_after_pencil=args.wait_after_pencil,
        wait_after_confirm=args.wait_after_confirm,
        start_scan=args.start_scan,
        already_on_detail=args.already_on_detail,
    )


def cmd_build_rank_data(args: argparse.Namespace) -> None:
    output = convert_pokeminers_game_master(
        args.game_master, args.output, max_level=args.max_level
    )
    print(f"Rank data written: {output}")


def cmd_rank(args: argparse.Namespace) -> None:
    data = PokemonData(args.data)
    ranks = all_league_ranks(
        data, args.species, args.attack, args.defense, args.hp,
        form=args.form, max_level=args.max_level,
    )
    for league, entry in ranks.items():
        print(
            f"{league}: rank {entry.rank}/4096; {entry.percentile:.3f}%; "
            f"level {entry.level:.1f}; CP {entry.cp}; stat product {entry.stat_product:.3f}"
        )
    if args.evolutions:
        for (species, form), evolved_ranks in evolution_league_ranks(
            data, args.species, args.attack, args.defense, args.hp,
            form=args.form, max_level=args.max_level,
            min_cap_ratio=args.min_cap_ratio,
        ).items():
            for league, entry in evolved_ranks.items():
                print(
                    f"{species} ({form}) {league}: rank {entry.rank}/4096; "
                    f"{entry.percentile:.3f}%; level {entry.level:.1f}; CP {entry.cp}"
                )
    if args.suggest_name:
        name, selected = suggested_pvp_name(
            data, args.species, args.attack, args.defense, args.hp,
            form=args.form, max_level=args.max_level,
            min_cap_ratio=args.min_cap_ratio,
        )
        print(f"Suggested name: {name or '(no cap-relevant GL/UL candidate)'}")
        for league, candidate in selected.items():
            print(f"  {league}: {candidate.species} ({candidate.form}), stage {candidate.evolution_stage}")


def cmd_rename(args: argparse.Namespace) -> None:
    count = args.count if args.count is not None else 5
    run_rename(
        count=count,
        adb_serial=args.adb_serial,
        wait_after_pencil=args.wait_after_pencil,
        wait_after_appraise_before_triangle_reveal=args.wait_after_appraise_before_triangle_reveal,
        wait_after_triangle_reveal=args.wait_after_triangle_reveal,
        execute=not args.dry_run,
    )


def cmd_workflow(args: argparse.Namespace) -> None:
    if args.config:
        config = AppConfig.from_json(args.config)
        args.adb_serial = args.adb_serial or config.adb_serial
        args.count = args.count if args.count is not None else config.scan.count
        args.wait_before_ocr = config.scan.wait_before_ocr
        args.wait_after_next = config.scan.wait_after_next
        args.wait_after_pencil = config.rename.wait_after_pencil
        args.wait_after_appraise_before_triangle_reveal = config.rename.wait_after_appraise_before_triangle_reveal
        args.wait_after_triangle_reveal = config.rename.wait_after_triangle_reveal
    else:
        args.count = args.count if args.count is not None else 5

    run_workflow(
        count=args.count,
        adb_serial=args.adb_serial,
        execute=not args.dry_run,
        wait_before_ocr=args.wait_before_ocr,
        wait_after_next=args.wait_after_next,
        wait_after_pencil=args.wait_after_pencil,
        wait_after_appraise_before_triangle_reveal=args.wait_after_appraise_before_triangle_reveal,
        wait_after_triangle_reveal=args.wait_after_triangle_reveal,
        clean_start=not getattr(args, "no_clean_start", False),
        rename_after_scan=args.rename_after_scan and not args.no_rename,
    )


def cmd_init_config(args: argparse.Namespace) -> None:
    AppConfig().to_json(Path(args.output))
    print(f"Wrote {args.output}")


def cmd_doctor(args: argparse.Namespace) -> None:
    raise SystemExit(run_doctor(include_device=not args.no_device))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
