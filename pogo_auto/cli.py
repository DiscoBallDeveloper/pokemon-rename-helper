from __future__ import annotations

import argparse
from pathlib import Path

from .cleanup import clean_runtime_outputs
from .adb import AdbTarget, connect_wifi, kill_pokegenie, list_devices, pair_wifi, require_device
from .settings import AppConfig
from .workflow import run_rename, run_scan, run_workflow
from .doctor import run_doctor


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

    p = sub.add_parser("rename", help="Run rename pass only.")
    add_common_run_args(p)
    add_rename_timing_args(p)
    p.set_defaults(func=cmd_rename)

    p = sub.add_parser("workflow", help="Run scan → kill Poke Genie → rename.")
    add_common_run_args(p)
    p.add_argument("--no-clean-start", action="store_true", help="Do not remove old screenshots/logs before starting.")
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
