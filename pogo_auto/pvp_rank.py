from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SpeciesStats:
    species: str
    form: str
    base_attack: int
    base_defense: int
    base_stamina: int


@dataclass(frozen=True)
class RankEntry:
    rank: int
    attack_iv: int
    defense_iv: int
    stamina_iv: int
    level: float
    cp: int
    attack: float
    defense: float
    hp: int
    stat_product: float
    percentile: float


class PokemonData:
    """
    Small, explicit data adapter.

    JSON format:
      {
        "cpm": {"1.0": 0.094, "1.5": ...},
        "species": [
          {"species":"Azumarill","form":"NORMAL",
           "base_attack":112,"base_defense":152,"base_stamina":225}
        ]
      }
    """

    def __init__(self, path: str | Path) -> None:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.cpm = {float(k): float(v) for k, v in payload["cpm"].items()}
        self.species = {
            (row["species"].casefold(), row.get("form", "NORMAL").casefold()):
            SpeciesStats(
                species=row["species"],
                form=row.get("form", "NORMAL"),
                base_attack=int(row["base_attack"]),
                base_defense=int(row["base_defense"]),
                base_stamina=int(row["base_stamina"]),
            )
            for row in payload["species"]
        }
        self.evolutions = {
            (row["species"].casefold(), row.get("form", "NORMAL").casefold()): tuple(
                (item["species"], item.get("form", "NORMAL"))
                for item in row.get("evolutions", [])
            )
            for row in payload["species"]
        }

    def get(self, species: str, form: str = "NORMAL") -> SpeciesStats:
        key = (species.casefold(), form.casefold())
        try:
            return self.species[key]
        except KeyError as exc:
            raise KeyError(f"Missing base stats for {species!r}, form {form!r}") from exc

    def evolution_descendants(self, species: str, form: str = "NORMAL") -> tuple[SpeciesStats, ...]:
        """Return all reachable evolutions, preserving the Pokémon GO form."""
        pending = [(species, form)]
        seen = {(species.casefold(), form.casefold())}
        result: list[SpeciesStats] = []
        while pending:
            current = pending.pop()
            key = (current[0].casefold(), current[1].casefold())
            for next_species, next_form in self.evolutions.get(key, ()):
                next_key = (next_species.casefold(), next_form.casefold())
                if next_key in seen:
                    continue
                seen.add(next_key)
                try:
                    stats = self.get(next_species, next_form)
                except KeyError:
                    continue
                result.append(stats)
                pending.append((stats.species, stats.form))
        return tuple(result)


def combat_power(
    stats: SpeciesStats,
    attack_iv: int,
    defense_iv: int,
    stamina_iv: int,
    cpm: float,
) -> int:
    raw = (
        (stats.base_attack + attack_iv)
        * math.sqrt(stats.base_defense + defense_iv)
        * math.sqrt(stats.base_stamina + stamina_iv)
        * cpm * cpm
        / 10.0
    )
    return max(10, int(math.floor(raw)))


def adjusted_stats(
    stats: SpeciesStats,
    attack_iv: int,
    defense_iv: int,
    stamina_iv: int,
    cpm: float,
) -> tuple[float, float, int]:
    attack = (stats.base_attack + attack_iv) * cpm
    defense = (stats.base_defense + defense_iv) * cpm
    hp = max(10, int(math.floor((stats.base_stamina + stamina_iv) * cpm)))
    return attack, defense, hp


def best_level(
    stats: SpeciesStats,
    ivs: tuple[int, int, int],
    cpm_by_level: dict[float, float],
    cp_cap: int | None,
    max_level: float,
) -> tuple[float, int, float, float, int, float]:
    atk_iv, def_iv, sta_iv = ivs
    eligible = sorted(
        (level, cpm)
        for level, cpm in cpm_by_level.items()
        if level <= max_level
    )
    chosen = None
    for level, cpm in eligible:
        cp = combat_power(stats, atk_iv, def_iv, sta_iv, cpm)
        if cp_cap is not None and cp > cp_cap:
            break
        attack, defense, hp = adjusted_stats(
            stats, atk_iv, def_iv, sta_iv, cpm
        )
        chosen = (level, cp, attack, defense, hp, attack * defense * hp)
    if chosen is None:
        level, cpm = eligible[0]
        cp = combat_power(stats, atk_iv, def_iv, sta_iv, cpm)
        attack, defense, hp = adjusted_stats(stats, atk_iv, def_iv, sta_iv, cpm)
        chosen = (level, cp, attack, defense, hp, attack * defense * hp)
    return chosen


@lru_cache(maxsize=512)
def build_rank_table(
    stats: SpeciesStats,
    cpm_items: tuple[tuple[float, float], ...],
    cp_cap: int | None,
    max_level: float,
) -> tuple[RankEntry, ...]:
    cpm_by_level = dict(cpm_items)
    rows = []
    for attack_iv in range(16):
        for defense_iv in range(16):
            for stamina_iv in range(16):
                level, cp, attack, defense, hp, product = best_level(
                    stats,
                    (attack_iv, defense_iv, stamina_iv),
                    cpm_by_level,
                    cp_cap,
                    max_level,
                )
                rows.append((
                    product, defense, hp, attack,
                    attack_iv, defense_iv, stamina_iv,
                    level, cp,
                ))

    # Standard stat-product ordering. Tie-breakers are deterministic and documented.
    rows.sort(
        key=lambda x: (x[0], x[1], x[2], x[3]),
        reverse=True,
    )

    total = len(rows)
    entries = []
    for index, row in enumerate(rows, start=1):
        product, defense, hp, attack, atk_iv, def_iv, sta_iv, level, cp = row
        entries.append(RankEntry(
            rank=index,
            attack_iv=atk_iv,
            defense_iv=def_iv,
            stamina_iv=sta_iv,
            level=level,
            cp=cp,
            attack=attack,
            defense=defense,
            hp=hp,
            stat_product=product,
            percentile=100.0 * (total - index + 1) / total,
        ))
    return tuple(entries)


def rank_ivs(
    data: PokemonData,
    species: str,
    attack_iv: int,
    defense_iv: int,
    stamina_iv: int,
    *,
    form: str = "NORMAL",
    league: str,
    max_level: float = 50.0,
) -> RankEntry:
    league_key = league.upper()
    caps = {"GL": 1500, "UL": 2500, "ML": None}
    if league_key not in caps:
        raise ValueError("league must be GL, UL, or ML")

    for value in (attack_iv, defense_iv, stamina_iv):
        if not 0 <= value <= 15:
            raise ValueError("IV values must be in 0..15")

    stats = data.get(species, form)
    table = build_rank_table(
        stats,
        tuple(sorted(data.cpm.items())),
        caps[league_key],
        max_level,
    )
    wanted = (attack_iv, defense_iv, stamina_iv)
    return next(
        row for row in table
        if (row.attack_iv, row.defense_iv, row.stamina_iv) == wanted
    )


def all_league_ranks(
    data: PokemonData,
    species: str,
    attack_iv: int,
    defense_iv: int,
    stamina_iv: int,
    *,
    form: str = "NORMAL",
    max_level: float = 50.0,
) -> dict[str, RankEntry]:
    return {
        league: rank_ivs(
            data, species, attack_iv, defense_iv, stamina_iv,
            form=form, league=league, max_level=max_level,
        )
        for league in ("GL", "UL", "ML")
    }


def evolution_league_ranks(
    data: PokemonData,
    species: str,
    attack_iv: int,
    defense_iv: int,
    stamina_iv: int,
    *,
    form: str = "NORMAL",
    max_level: float = 50.0,
    min_cap_ratio: float = 0.90,
) -> dict[tuple[str, str], dict[str, RankEntry]]:
    """Rank evolutions that can reach a meaningful fraction of each cap."""
    caps = {"GL": 1500, "UL": 2500, "ML": None}
    result: dict[tuple[str, str], dict[str, RankEntry]] = {}
    for evolved in data.evolution_descendants(species, form):
        ranks = all_league_ranks(
            data, evolved.species, attack_iv, defense_iv, stamina_iv,
            form=evolved.form, max_level=max_level,
        )
        viable: dict[str, RankEntry] = {}
        for league, entry in ranks.items():
            cap = caps[league]
            if cap is None or entry.cp >= cap * min_cap_ratio:
                viable[league] = entry
        if viable:
            result[(evolved.species, evolved.form)] = viable
    return result
