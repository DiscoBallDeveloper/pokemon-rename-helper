import json

from pogo_auto.pvp_rank import PokemonData, all_league_ranks


def test_rank_engine_returns_all_leagues(tmp_path):
    # Tiny CPM table is enough to validate enumeration and lookup mechanics.
    data_path = tmp_path / "pokemon.json"
    data_path.write_text(json.dumps({
        "cpm": {"1.0": 0.094, "50.0": 0.84029999},
        "species": [{
            "species": "Examplemon",
            "form": "NORMAL",
            "base_attack": 120,
            "base_defense": 140,
            "base_stamina": 160
        }]
    }))
    data = PokemonData(data_path)
    ranks = all_league_ranks(data, "Examplemon", 0, 15, 15)
    assert set(ranks) == {"GL", "UL", "ML"}
    assert all(1 <= x.rank <= 4096 for x in ranks.values())
