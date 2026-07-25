from pogo_auto.pvp_naming import LeagueNameCandidate, encode_league_segment
from pogo_auto.pvp_rank import RankEntry


def entry(rank: int, percentile: float) -> RankEntry:
    return RankEntry(rank, 0, 0, 0, 50.0, 1500, 1.0, 1.0, 1, 1.0, percentile)


def test_rank_name_uses_raw_rank_through_999_then_percentile():
    assert encode_league_segment(LeagueNameCandidate("GL", "X", "NORMAL", 1, entry(123, 97.0))) == "G1231"
    assert encode_league_segment(LeagueNameCandidate("UL", "X", "NORMAL", 2, entry(2822, 31.128))) == "U031%2"
