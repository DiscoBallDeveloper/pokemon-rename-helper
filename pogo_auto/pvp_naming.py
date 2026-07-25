from __future__ import annotations

from dataclasses import dataclass

from .pvp_rank import PokemonData, RankEntry, all_league_ranks


@dataclass(frozen=True)
class LeagueNameCandidate:
    league: str
    species: str
    form: str
    evolution_stage: int
    entry: RankEntry


def encode_league_segment(candidate: LeagueNameCandidate) -> str:
    """Encode one league into at most six Pokémon-name characters."""
    prefix = candidate.league[0]
    stage = str(candidate.evolution_stage)
    if candidate.entry.rank <= 999:
        return f"{prefix}{candidate.entry.rank:03d}{stage}"
    percentile = min(100, max(0, round(candidate.entry.percentile)))
    return f"{prefix}{percentile:03d}%{stage}"


def suggested_pvp_name(
    data: PokemonData,
    species: str,
    attack_iv: int,
    defense_iv: int,
    hp_iv: int,
    *,
    form: str = "NORMAL",
    max_level: float = 50.0,
    min_cap_ratio: float = 0.90,
) -> tuple[str, dict[str, LeagueNameCandidate]]:
    """Return a <=12-character GL/UL name and the selected evidence.

    For each league the best (lowest raw rank) cap-relevant species in the
    current evolution family wins.  Evolution stage remains in the compact
    name, so the result is still actionable when a base form and evolution
    differ in relevance.
    """
    caps = {"GL": 1500, "UL": 2500}
    family = [(data.get(species, form), 0)]
    pending = [(species, form, 0)]
    seen = {(species.casefold(), form.casefold())}
    while pending:
        current_species, current_form, stage = pending.pop()
        key = (current_species.casefold(), current_form.casefold())
        for next_species, next_form in data.evolutions.get(key, ()):
            next_key = (next_species.casefold(), next_form.casefold())
            if next_key in seen:
                continue
            seen.add(next_key)
            try:
                evolved = data.get(next_species, next_form)
            except KeyError:
                continue
            family.append((evolved, stage + 1))
            pending.append((evolved.species, evolved.form, stage + 1))

    selected: dict[str, LeagueNameCandidate] = {}
    for evolved, stage in family:
        ranks = all_league_ranks(
            data, evolved.species, attack_iv, defense_iv, hp_iv,
            form=evolved.form, max_level=max_level,
        )
        for league, cap in caps.items():
            entry = ranks[league]
            if entry.cp < cap * min_cap_ratio:
                continue
            candidate = LeagueNameCandidate(league, evolved.species, evolved.form, stage, entry)
            if league not in selected or candidate.entry.rank < selected[league].entry.rank:
                selected[league] = candidate
    name = "".join(encode_league_segment(selected[league]) for league in ("GL", "UL") if league in selected)
    if len(name) > 12:
        raise ValueError(f"Suggested name exceeds Pokémon GO's 12-character limit: {name}")
    return name, selected
