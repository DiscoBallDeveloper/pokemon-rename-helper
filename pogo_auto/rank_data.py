from __future__ import annotations

"""Convert a pinned PokeMiners Game Master into rank-engine input data."""

import json
import math
from pathlib import Path
from typing import Any


def _display_name(pokemon_id: str) -> str:
    # Native OCR uses normal title words for the overwhelming majority of IDs.
    # Keep the original ID too so an unsupported punctuation/form name fails
    # safely instead of silently selecting an unrelated species.
    return pokemon_id.replace("_", " ").title()


def _form_name(pokemon_id: str, form: str | None) -> str:
    if not form or form == "FORM_UNSET" or form == f"{pokemon_id}_NORMAL":
        return "NORMAL"
    prefix = f"{pokemon_id}_"
    return form.removeprefix(prefix) if form.startswith(prefix) else form


def convert_pokeminers_game_master(
    game_master_path: str | Path,
    output_path: str | Path,
    *,
    max_level: int = 50,
) -> Path:
    """Write the complete species/base-stat/half-level-CPM rank data file."""
    source = Path(game_master_path)
    payload: list[dict[str, Any]] = json.loads(source.read_text(encoding="utf-8"))
    multipliers: list[float] | None = None
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in payload:
        data = entry.get("data", {})
        player_level = data.get("playerLevel", {})
        if "cpMultiplier" in player_level:
            multipliers = [float(value) for value in player_level["cpMultiplier"]]
        settings = data.get("pokemonSettings", {})
        stats = settings.get("stats")
        pokemon_id = settings.get("pokemonId")
        if not pokemon_id or not stats or not all(key in stats for key in ("baseAttack", "baseDefense", "baseStamina")):
            continue
        form = _form_name(pokemon_id, settings.get("form"))
        key = (pokemon_id, form)
        # Prefer explicit form entries (for example WOOLOO_NORMAL) over the
        # legacy generic record when both contain the same stats.
        if key not in candidates or settings.get("form"):
            candidates[key] = {
                "species": _display_name(pokemon_id),
                "form": form,
                "base_attack": int(stats["baseAttack"]),
                "base_defense": int(stats["baseDefense"]),
                "base_stamina": int(stats["baseStamina"]),
                "game_master_id": pokemon_id,
                "evolutions": [
                    {
                        "species_id": branch["evolution"],
                        "form": _form_name(branch["evolution"], branch.get("form")),
                    }
                    for branch in settings.get("evolutionBranch", [])
                    if branch.get("evolution")
                ],
            }
    if multipliers is None or len(multipliers) < max_level:
        raise ValueError("Game Master has no complete playerLevel.cpMultiplier table")
    cpm: dict[str, float] = {}
    for level in range(1, max_level + 1):
        cpm[f"{level}.0"] = multipliers[level - 1]
        if level < max_level:
            # Pokémon GO's half-level CPM is the geometric mean of adjacent
            # whole-level multipliers.
            cpm[f"{level}.5"] = math.sqrt(multipliers[level - 1] * multipliers[level])
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Resolve Game Master IDs to the display names used by this rank file.
    id_to_name = {row["game_master_id"]: row["species"] for row in candidates.values()}
    species_rows = []
    for row in candidates.values():
        row = dict(row)
        row["evolutions"] = [
            {"species": id_to_name[item["species_id"]], "form": item["form"]}
            for item in row.pop("evolutions")
            if item["species_id"] in id_to_name
        ]
        species_rows.append(row)
    output.write_text(json.dumps({
        "dataset_version": "pokeminers-game-master",
        "source_file": source.name,
        "max_level": max_level,
        "cpm": cpm,
        "species": sorted(species_rows, key=lambda row: (row["species"], row["form"])),
    }, indent=2), encoding="utf-8")
    return output
