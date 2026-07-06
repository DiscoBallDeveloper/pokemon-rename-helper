from __future__ import annotations

from dataclasses import dataclass

from .adb import AdbTarget


@dataclass(frozen=True)
class AndroidApps:
    pokemon_go_package: str = "com.nianticlabs.pokemongo"
    pokegenie_packages: tuple[str, ...] = ("com.cjin.pokegenie.standard", "com.cjin.pokegenie")


def force_stop_packages(target: AdbTarget, packages: tuple[str, ...] | list[str]) -> None:
    for package in packages:
        target.run("shell", "am", "force-stop", package, check=False)


def focus_pokemon_go(target: AdbTarget, package: str = AndroidApps().pokemon_go_package) -> None:
    target.run("shell", "monkey", "-p", package, "1", check=False)


def kill_pokegenie_and_focus_game(target: AdbTarget, apps: AndroidApps = AndroidApps()) -> None:
    force_stop_packages(target, apps.pokegenie_packages)
    focus_pokemon_go(target, apps.pokemon_go_package)
