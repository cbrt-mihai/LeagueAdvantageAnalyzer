import sys
import json
import datetime
import os

from riot_api import (
    get_account_by_riot_id,
    get_match_ids,
    get_match,
    get_timeline,
)

from comparisons import (
    ComparisonRequest,
    compare_timeline,
    parse_time,
)

from models import PlayerSnapshot, TeamObjectiveSnapshot
from advantages import build_match_analysis, STAT_NAMES, OBJECTIVE_NAMES

# All stats are reported by default.  Override this list to restrict output.
REPORT_STATS = STAT_NAMES

# Report-facing team labels are intentionally independent from Riot's internal
# team IDs (100/200). Blue is always the script runner's team; Red is the opponent.
REPORT_BLUE_TEAM = 100
REPORT_RUNNER_PARTICIPANT_ID = None
LANE_ORDER = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

def set_report_perspective(runner_team, runner_participant_id=None):
    global REPORT_BLUE_TEAM, REPORT_RUNNER_PARTICIPANT_ID
    REPORT_BLUE_TEAM = runner_team
    REPORT_RUNNER_PARTICIPANT_ID = runner_participant_id

def team_label(team_id):
    return "Blue" if team_id == REPORT_BLUE_TEAM else "Red"

def ordered_player_infos(players):
    lane_rank = {lane: i for i, lane in enumerate(LANE_ORDER)}
    return sorted(
        players.values(),
        key=lambda p: (
            0 if p["participant_id"] == REPORT_RUNNER_PARTICIPANT_ID else 1,
            0 if p["team"] == REPORT_BLUE_TEAM else 1,
            lane_rank.get(p["lane"], 99),
            p["participant_id"],
        ),
    )

def ordered_snapshots(players):
    lane_rank = {lane: i for i, lane in enumerate(LANE_ORDER)}
    return sorted(
        players,
        key=lambda p: (
            0 if p.participant_id == REPORT_RUNNER_PARTICIPANT_ID else 1,
            0 if p.team == REPORT_BLUE_TEAM else 1,
            lane_rank.get(p.lane, 99),
            p.participant_id,
        ),
    )

# Updated thresholds to include combat metrics
IMPACTFUL_THRESHOLDS = {
    "gold": 500,
    "xp": 300,
    "cs": 10,
    "level": 1,
    "kills": 1,
    "deaths": 1,
    "assists": 2,
    "kda": 1.0,
    "gold_per_minute": 50,
    "cs_per_minute": 1.0,
    "attack_damage": 20,
    "ability_power": 30,
    "health": 200,
    "max_health": 200,
    "armor": 10,
    "magic_resist": 10,
    "attack_speed": 0.1,
    "movement_speed": 10,
    "ability_haste": 10,
    "armor_pen": 5,
    "armor_pen_percent": 5,
    "magic_pen": 5,
    "magic_pen_percent": 5,
    "health_regen": 5,
    "lifesteal": 5,
    "omnivamp": 3,
}

IMPACTFUL_OBJECTIVE_THRESHOLDS = {
    "turrets": 1,
    "outer_turrets": 1,
    "inner_turrets": 1,
    "inhibitor_turrets": 1,
    "nexus_turrets": 1,
    "inhibitors": 1,
    "dragons": 1,
    "elemental_drakes": 1,
    "heralds": 1,
    "barons": 1,
    "grubs": 1,
}

ADVANCED_STAT_KEYS = [
    "kp_pct", "gold_share", "dmg_share",
    "gold_efficiency", "vision_score", "wards_placed", "wards_killed"
]


def extract_kda_from_events(events, up_to_timestamp):
    """Accumulate kills, deaths, assists, wards, and running vision score per participant up to timestamp."""
    stats = {
        i: {
            "kills": 0,
            "deaths": 0,
            "assists": 0,
            "wards_placed": 0,
            "wards_killed": 0,
            "vision_score": 0.0,
        }
        for i in range(1, 11)
    }

    for event in events:
        if event.get("timestamp", 0) > up_to_timestamp:
            break

        event_type = event.get("type")

        if event_type == "CHAMPION_KILL":
            killer_id = event.get("killerId", 0)
            victim_id = event.get("victimId", 0)
            assisters = event.get("assistingParticipantIds", [])

            if killer_id in stats:
                stats[killer_id]["kills"] += 1
            if victim_id in stats:
                stats[victim_id]["deaths"] += 1
            for assist_id in assisters:
                if assist_id in stats:
                    stats[assist_id]["assists"] += 1

        elif event_type == "WARD_PLACED":
            creator_id = event.get("creatorId", 0)
            if creator_id in stats:
                stats[creator_id]["wards_placed"] += 1
                # Increment running vision score estimate per ward placed
                stats[creator_id]["vision_score"] += 1.0

        elif event_type == "WARD_KILL":
            killer_id = event.get("killerId", 0)
            if killer_id in stats:
                stats[killer_id]["wards_killed"] += 1
                # Increment running vision score estimate per ward cleared
                stats[killer_id]["vision_score"] += 1.5

    return stats


# ---------------------------------------------------------------------------
# Dual-output writer
# ---------------------------------------------------------------------------

class Writer:
    """Writes every line to the console AND to a text file simultaneously."""

    def __init__(self, filepath: str):
        self._file = open(filepath, "w", encoding="utf-8")

    def print(self, *args, **kwargs):
        # Always write to stdout
        print(*args, **kwargs)
        # Mirror to file (redirect stdout temporarily)
        kwargs.pop("file", None)
        print(*args, file=self._file, **kwargs)

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_metric(metric):
    ratio = metric["ratio"]
    ratio_text = "N/A" if ratio is None else f"{ratio:.2f}x"
    diff_val = metric["difference"]

    return (
        f"{metric['value']:>9.2f}"
        f" vs {metric['reference']:>9.2f}"
        f"   diff {diff_val:>+9.2f}"
        f"   {ratio_text:>7}"
    )


# ---------------------------------------------------------------------------
# Per-interval report
# ---------------------------------------------------------------------------

def calculate_player_overall_advantage(player_analysis):
    """
    Backwards-compatible wrapper used by existing ranking code.
    """
    return calculate_player_advantage_score(player_analysis)


def get_ranked_players(analysis):
    """Returns player analyses sorted from best overall performance to worst."""
    return sorted(
        analysis.players,
        key=calculate_player_overall_advantage,
        reverse=True
    )


def print_advantage_report(analysis, w: Writer, stats=None):
    if stats is None:
        stats = REPORT_STATS

    minute = analysis.game.timestamp / 1000 / 60

    w.print("\n" + "=" * 110)
    w.print(f"MATCH ADVANTAGE @ {minute:5.1f} min")
    w.print("=" * 110)

    team = analysis.team_comparisons

    w.print(
        f"\nTEAM ADVANTAGE"
        f" ({team_label(team.own_team.team)} vs {team_label(team.opponent_team.team)})"
    )
    w.print("  " + "-" * 100)

    for stat in stats:
        metric = team.comparisons[stat]["vs_opponent_team"]
        w.print(f"  {stat:<24} {format_metric(metric)}")

    # Objective comparisons
    w.print("\nOBJECTIVE ADVANTAGE")
    w.print("  " + "-" * 100)

    for objective in OBJECTIVE_NAMES:
        metric = team.objective_comparisons[objective]
        w.print(f"  {objective:<24} {format_metric(metric)}")

    w.print("\nLANE ADVANTAGE (own lane total vs opponent lane total)")
    w.print("  " + "-" * 100)

    lane_order = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

    for lane_name in lane_order:
        lane = analysis.lanes.get(lane_name)

        if lane is None:
            continue

        lane_score = calculate_lane_advantage_score(lane)

        own_player = lane.own_lane.players[0]
        enemy_player = lane.opponent_lane.players[0]

        w.print(
            f"\n  {lane_name:<8}"
            f" {own_player.champion:<14} vs {enemy_player.champion:<14}"
            f"  Lane Advantage: {lane_score:+.1f}"
            f"  ({advantage_label(lane_score)})"
        )

        for stat in stats:
            metric = lane.comparisons[stat]["vs_opponent_lane"]["total"]
            w.print(f"    {stat:<22} {format_metric(metric)}")

    w.print("\nPLAYER ADVANTAGE (vs lane opponent)")
    w.print("  " + "-" * 100)

    for player_analysis in get_ranked_players(analysis):
        player = player_analysis.player
        opponent = player_analysis.opponent
        player_score = calculate_player_advantage_score(player_analysis)

        w.print(
            f"\n  [{player.participant_id:>2}]"
            f" {player.champion:<14} vs {opponent.champion:<14}"
            f" ({player.lane})"
            f"  Advantage Score: {player_score:+.1f}"
            f"  [{champion_advantage_direction(player_score, player.team)}]"
        )

        for stat in stats:
            metric = player_analysis.comparisons[stat]["vs_opponent"]
            w.print(f"    {stat:<22} {format_metric(metric)}")


# ---------------------------------------------------------------------------
# Final / summary report helpers
# ---------------------------------------------------------------------------

def _collect_stat_series(analyses, get_diff_fn):
    """Return a list of (minute, diff) tuples across all analyses."""
    series = []
    for analysis in analyses:
        minute = analysis.game.timestamp / 1000 / 60
        diff = get_diff_fn(analysis)
        if diff is not None:
            series.append((minute, diff))
    return series


def _summarize_series(series):
    if not series:
        return None

    diffs = [d for _, d in series]
    avg_diff = sum(diffs) / len(diffs)
    peak_minute, peak_diff = max(series, key=lambda t: abs(t[1]))
    final_minute, final_diff = series[-1]

    return {
        "avg": avg_diff,
        "peak": peak_diff,
        "peak_minute": peak_minute,
        "final": final_diff,
        "final_minute": final_minute,
    }


def _print_summary_row(label, summary, w: Writer, indent="  "):
    if summary is None:
        w.print(f"{indent}{label:<24}  no data")
        return

    avg = summary["avg"]
    peak = summary["peak"]
    peak_min = summary["peak_minute"]
    final = summary["final"]
    final_min = summary["final_minute"]

    w.print(
        f"{indent}{label:<24}"
        f"  avg {avg:>+10.2f}"
        f"   peak {peak:>+10.2f} @ {peak_min:5.1f}m"
        f"   final {final:>+10.2f} @ {final_min:5.1f}m"
    )


# ---------------------------------------------------------------------------
# Player extremes & stat spectrum reports
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Advantage Score
# ---------------------------------------------------------------------------
#
# Advantage Score is a normalized measure from -100 to +100.
#
# For PLAYER / CHAMPION scores:
#   +100 = extremely ahead of lane opponent
#      0 = even
#   -100 = extremely behind lane opponent
#
# For TEAM / LANE scores:
#   Positive = Blue / script-runner team advantage
#   Negative = Red advantage
#
# Each stat difference is normalized against a meaningful threshold,
# capped to [-1, +1], and then averaged.
#
# Deaths are inverted because fewer deaths is better.
#
LOWER_IS_BETTER = {"deaths"}

ADVANTAGE_SCORE_THRESHOLDS = {
    # Economy / progression
    "gold": 500.0,
    "gold_per_minute": 50.0,
    "xp": 300.0,
    "cs": 10.0,
    "cs_per_minute": 1.0,
    "level": 1.0,

    # Combat
    "kills": 1.0,
    "deaths": 1.0,
    "assists": 2.0,
    "kda": 1.0,

    # Combat stats
    "attack_damage": 20.0,
    "ability_power": 30.0,
    "health": 200.0,
    "max_health": 200.0,
    "armor": 10.0,
    "magic_resist": 10.0,
    "attack_speed": 0.10,
    "movement_speed": 10.0,
    "ability_haste": 10.0,
    "armor_pen": 5.0,
    "armor_pen_percent": 5.0,
    "magic_pen": 5.0,
    "magic_pen_percent": 5.0,
    "health_regen": 5.0,
    "lifesteal": 5.0,
    "omnivamp": 3.0,

    # Advanced / efficiency
    "kp_pct": 5.0,
    "gold_share": 5.0,
    "dmg_share": 5.0,
    "gold_efficiency": 0.25,
    "vision_score": 3.0,
    "wards_placed": 2.0,
    "wards_killed": 2.0,
}

OBJECTIVE_ADVANTAGE_THRESHOLDS = {
    objective: 1.0
    for objective in OBJECTIVE_NAMES
}


def _normalized_advantage(difference, threshold):
    """
    Convert a raw difference into a bounded [-1, +1] advantage value.
    """
    if threshold is None or threshold <= 0:
        return 0.0

    return max(-1.0, min(1.0, difference / threshold))


def _score_from_differences(differences):
    """
    Convert a collection of normalized differences into a score from -100
    to +100.
    """
    if not differences:
        return 0.0

    return (
        sum(differences) / len(differences)
    ) * 100.0


def calculate_player_advantage_score(player_analysis):
    """
    Final Advantage Score for a champion/player.

    Positive = this champion is ahead of their lane opponent.
    Negative = this champion is behind their lane opponent.
    """
    normalized = []

    for stat, metric in player_analysis.comparisons.items():
        threshold = ADVANTAGE_SCORE_THRESHOLDS.get(stat)

        if threshold is None:
            continue

        difference = metric["vs_opponent"]["difference"]

        if stat in LOWER_IS_BETTER:
            difference = -difference

        normalized.append(
            _normalized_advantage(difference, threshold)
        )

    return _score_from_differences(normalized)


def calculate_pairwise_player_score(player, opponent):
    """
    Calculate a directional Advantage Score for one player relative to
    another player.

    Positive = player has the advantage over opponent.
    Negative = player is behind opponent.

    Each stat is normalized independently using the existing
    ADVANTAGE_SCORE_THRESHOLDS, then the normalized stat scores are
    averaged.

    This is intentionally independent of the player's normal lane-opponent
    comparison.
    """
    normalized = []

    for stat, threshold in ADVANTAGE_SCORE_THRESHOLDS.items():
        if threshold is None:
            continue

        player_value = getattr(player, stat, 0.0)
        opponent_value = getattr(opponent, stat, 0.0)

        difference = player_value - opponent_value

        if stat in LOWER_IS_BETTER:
            difference = -difference

        normalized.append(
            _normalized_advantage(difference, threshold)
        )

    return _score_from_differences(normalized)


def calculate_relative_player_score(player, comparison_pool):
    """
    Calculate a player's Advantage Score relative to every other player
    in the supplied comparison pool.

    The player's score is the mean of all pairwise normalized comparisons.

    Examples:
        Lane: player vs the other player(s) in the same lane.
        Team: player vs every teammate.
        Game: player vs every other player in the game.

    Returns:
        A score from -100 to +100.
    """
    opponents = [
        opponent
        for opponent in comparison_pool
        if opponent.participant_id != player.participant_id
    ]

    if not opponents:
        return 0.0

    pairwise_scores = [
        calculate_pairwise_player_score(player, opponent)
        for opponent in opponents
    ]

    return sum(pairwise_scores) / len(pairwise_scores)


def calculate_contextual_player_scores(analysis):
    """
    Calculate three different player Advantage Scores for the final
    rankings:

        lane_score  = player vs every other player in their lane
        team_score  = player vs every other player on their team
        game_score  = player vs every other player in the game

    Returns:
        {
            participant_id: {
                "player_analysis": ...,
                "lane_score": ...,
                "team_score": ...,
                "game_score": ...,
            }
        }
    """
    players = list(analysis.game.players)

    result = {}

    for player in players:
        lane_pool = [
            other
            for other in players
            if other.lane == player.lane
        ]

        team_pool = [
            other
            for other in players
            if other.team == player.team
        ]

        game_pool = players

        result[player.participant_id] = {
            "player_analysis": _get_player_analysis(
                analysis,
                player.participant_id,
            ),
            "lane_score": calculate_relative_player_score(
                player,
                lane_pool,
            ),
            "team_score": calculate_relative_player_score(
                player,
                team_pool,
            ),
            "game_score": calculate_relative_player_score(
                player,
                game_pool,
            ),
        }

    return result


def calculate_lane_advantage_score(lane_analysis):
    """
    Final Advantage Score for a lane.

    Positive = Blue/script-runner lane advantage.
    Negative = Red lane advantage.
    """
    normalized = []

    for stat, comparison in lane_analysis.comparisons.items():
        threshold = ADVANTAGE_SCORE_THRESHOLDS.get(stat)

        if threshold is None:
            continue

        difference = comparison["vs_opponent_lane"]["total"]["difference"]

        if stat in LOWER_IS_BETTER:
            difference = -difference

        normalized.append(
            _normalized_advantage(difference, threshold)
        )

    return _score_from_differences(normalized)


def calculate_team_advantage_score(team_analysis):
    """
    Final Advantage Score for the team.

    Positive = Blue/script-runner team advantage.
    Negative = Red advantage.

    70% player/stat advantage
    30% objective advantage
    """
    stat_scores = []

    for stat, comparison in team_analysis.comparisons.items():
        threshold = ADVANTAGE_SCORE_THRESHOLDS.get(stat)

        if threshold is None:
            continue

        difference = comparison["vs_opponent_team"]["difference"]

        if stat in LOWER_IS_BETTER:
            difference = -difference

        stat_scores.append(
            _normalized_advantage(difference, threshold)
        )

    objective_scores = []

    for objective, comparison in team_analysis.objective_comparisons.items():
        threshold = OBJECTIVE_ADVANTAGE_THRESHOLDS.get(objective)

        if threshold is None:
            continue

        difference = comparison["difference"]

        objective_scores.append(
            _normalized_advantage(difference, threshold)
        )

    stat_score = _score_from_differences(stat_scores)
    objective_score = _score_from_differences(objective_scores)

    if stat_scores and objective_scores:
        return (
            stat_score * 0.70
            + objective_score * 0.30
        )

    if stat_scores:
        return stat_score

    if objective_scores:
        return objective_score

    return 0.0


def advantage_label(score):
    """
    Human-readable interpretation of an Advantage Score.
    """
    if score >= 50:
        return "Strong Blue advantage"
    if score >= 20:
        return "Blue advantage"
    if score > 5:
        return "Slight Blue advantage"
    if score <= -50:
        return "Strong Red advantage"
    if score <= -20:
        return "Red advantage"
    if score < -5:
        return "Slight Red advantage"

    return "Even"


def champion_advantage_direction(score, team_id):
    """
    Returns the side-relative interpretation for a champion.

    Champion scores are player-relative:
      positive = that champion is ahead of their opponent.

    This is intentionally different from the Blue-centric team/lane score.
    """
    if score > 5:
        return "Ahead"
    if score < -5:
        return "Behind"
    return "Even"


def format_advantage_score(score):
    """
    Compact report representation.
    """
    if score > 5:
        return f"{score:+6.1f}  ↑"
    if score < -5:
        return f"{score:+6.1f}  ↓"
    return f"{score:+6.1f}  ="


def get_stat_extremes(players, stat):
    """Finds best and worst values, accounting for stat direction and filtering non-distinct values."""
    values = [getattr(p, stat) for p in players]
    min_val, max_val = min(values), max(values)

    # Ignore if all players share the exact same value (e.g., all 0 AH at min 1)
    if min_val == max_val:
        return None, None

    if stat in LOWER_IS_BETTER:
        best_val, worst_val = min_val, max_val
    else:
        best_val, worst_val = max_val, min_val

    best_players = [p for p in players if getattr(p, stat) == best_val]
    worst_players = [p for p in players if getattr(p, stat) == worst_val]

    return (best_val, best_players), (worst_val, worst_players)


def print_player_extremes(analysis, w: Writer, stats=None):
    """For each player, print which stats they were best/worst at, supporting ties."""
    if stats is None:
        stats = REPORT_STATS

    players = analysis.game.players
    best_map = {p.participant_id: [] for p in players}
    worst_map = {p.participant_id: [] for p in players}

    for stat in stats:
        res = get_stat_extremes(players, stat)
        if not res or res[0] is None:
            continue

        (best_val, best_players), (worst_val, worst_players) = res

        for p in best_players:
            best_map[p.participant_id].append(f"{stat} ({best_val:.0f})")
        for p in worst_players:
            worst_map[p.participant_id].append(f"{stat} ({worst_val:.0f})")

    w.print("\nPLAYER EXTREMES (Best/Worst at each stat)")
    w.print("  " + "-" * 100)

    for player in sorted(players, key=lambda p: p.participant_id):
        pid = player.participant_id
        b_str = ", ".join(best_map[pid]) if best_map[pid] else "(none)"
        w_str = ", ".join(worst_map[pid]) if worst_map[pid] else "(none)"

        w.print(f"\n  [{pid:>2}] {player.champion:<14} ({team_label(player.team)}, {player.lane})")
        w.print(f"       BEST at:  {b_str}")
        w.print(f"       WORST at: {w_str}")


def print_stat_spectrum(analysis, w: Writer, stats=None):
    """For each stat, print all players ranked from best to worst."""
    if stats is None:
        stats = REPORT_STATS

    players = analysis.game.players

    w.print("\n\nSTAT SPECTRUM (Players ranked best → worst per stat)")
    w.print("  " + "-" * 100)

    for stat in stats:
        values = [(p, getattr(p, stat)) for p in players]
        values_sorted = sorted(values, key=lambda x: x[1], reverse=True)

        # Build the spectrum string
        spectrum_parts = []
        for player, value in values_sorted:
            spectrum_parts.append(f"{player.champion}({value:.0f})")

        spectrum_str = " > ".join(spectrum_parts)

        w.print(f"\n  {stat}:")
        w.print(f"    {spectrum_str}")


def write_player_extremes_report(analysis, match_id, timestamp_str, players_dict):
    """Write a separate file for player extremes."""
    filename = f"extremes_{match_id}_{timestamp_str}.txt"

    with Writer(filename) as w:
        w.print("\n" + "=" * 72)
        w.print("PLAYER EXTREMES REPORT")
        w.print("=" * 72)

        # Header: player roster
        w.print("\nPLAYERS")
        w.print("  " + "-" * 66)

        w.print(
            f"  {'ID':>2}  "
            f"{'Champion':<14} "
            f"{'Player':<22} "
            f"{'Team':<6} "
            f"{'Position':<10}"
        )

        w.print("  " + "-" * 66)

        for participant_id, player in sorted(players_dict.items(), key=lambda item: (0 if item[1]["participant_id"] == REPORT_RUNNER_PARTICIPANT_ID else 1, 0 if item[1]["team"] == REPORT_BLUE_TEAM else 1, item[1]["participant_id"])):
            w.print(
                f"  {participant_id:>2}  "
                f"{player['champion']:<14} "
                f"{player['name']:<22} "
                f"{team_label(player['team']):<6} "
                f"{player['lane']:<10}"
            )

        print_player_extremes(analysis, w)

        w.print("\n" + "=" * 72)
        w.print("END OF PLAYER EXTREMES REPORT")
        w.print("=" * 72)

    return filename


def write_stat_spectrum_report(analysis, match_id, timestamp_str, players_dict):
    """Write a separate file for stat spectrum."""
    filename = f"spectrum_{match_id}_{timestamp_str}.txt"

    with Writer(filename) as w:
        w.print("\n" + "=" * 72)
        w.print("STAT SPECTRUM REPORT")
        w.print("=" * 72)

        # Header: player roster
        w.print("\nPLAYERS")
        w.print("  " + "-" * 66)

        w.print(
            f"  {'ID':>2}  "
            f"{'Champion':<14} "
            f"{'Player':<22} "
            f"{'Team':<6} "
            f"{'Position':<10}"
        )

        w.print("  " + "-" * 66)

        for participant_id, player in sorted(players_dict.items(), key=lambda item: (0 if item[1]["participant_id"] == REPORT_RUNNER_PARTICIPANT_ID else 1, 0 if item[1]["team"] == REPORT_BLUE_TEAM else 1, item[1]["participant_id"])):
            w.print(
                f"  {participant_id:>2}  "
                f"{player['champion']:<14} "
                f"{player['name']:<22} "
                f"{team_label(player['team']):<6} "
                f"{player['lane']:<10}"
            )

        print_stat_spectrum(analysis, w)

        w.print("\n" + "=" * 72)
        w.print("END OF STAT SPECTRUM REPORT")
        w.print("=" * 72)

    return filename


# ---------------------------------------------------------------------------
# Short summary report - Average advantages per interval
# ---------------------------------------------------------------------------

def print_short_average_report(analyses, w: Writer, stats=None):
    """Print a condensed report showing average advantage at each interval for each stat."""
    if stats is None:
        stats = REPORT_STATS

    if not analyses:
        w.print("\nNo analyses to summarize.")
        return

    w.print("\n" + "=" * 110)
    w.print("SHORT REPORT: AVERAGE ADVANTAGE PER INTERVAL")
    w.print("=" * 110)

    # Team stats header
    w.print("\nTEAM STAT ADVANTAGES (Blue vs Red)")
    w.print("  " + "-" * 100)

    # Build header row with timestamps
    timestamps = [a.game.timestamp / 1000 / 60 for a in analyses]
    header = f"  {'Stat':<20}"
    for ts in timestamps:
        header += f" {ts:>6.0f}m"
    w.print(header)
    w.print("  " + "-" * 100)

    for stat in stats:
        row = f"  {stat:<20}"
        for analysis in analyses:
            diff = analysis.team_comparisons.comparisons[stat]["vs_opponent_team"]["difference"]
            row += f" {diff:>+7.0f}"
        w.print(row)

    # Objective advantages
    w.print("\nOBJECTIVE ADVANTAGES (Blue vs Red)")
    w.print("  " + "-" * 100)

    header = f"  {'Objective':<20}"
    for ts in timestamps:
        header += f" {ts:>6.0f}m"
    w.print(header)
    w.print("  " + "-" * 100)

    for objective in OBJECTIVE_NAMES:
        row = f"  {objective:<20}"
        for analysis in analyses:
            diff = analysis.team_comparisons.objective_comparisons[objective]["difference"]
            row += f" {diff:>+7.0f}"
        w.print(row)

    # Lane averages
    lane_order = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

    w.print("\nLANE ADVANTAGES (gold diff by lane)")
    w.print("  " + "-" * 100)

    header = f"  {'Lane':<20}"
    for ts in timestamps:
        header += f" {ts:>6.0f}m"
    w.print(header)
    w.print("  " + "-" * 100)

    for lane_name in lane_order:
        row = f"  {lane_name:<20}"
        for analysis in analyses:
            if lane_name in analysis.lanes:
                diff = analysis.lanes[lane_name].comparisons["gold"]["vs_opponent_lane"]["total"]["difference"]
                row += f" {diff:>+7.0f}"
            else:
                row += f" {'N/A':>7}"
        w.print(row)


# ---------------------------------------------------------------------------
# Impactful differences report
# ---------------------------------------------------------------------------

def print_impactful_differences_report(analyses, w: Writer, stats=None):
    """Print only the impactful differences: when they happened, between whom, and what stats."""
    if stats is None:
        stats = REPORT_STATS

    if not analyses:
        w.print("\nNo analyses to summarize.")
        return

    w.print("\n" + "=" * 110)
    w.print("IMPACTFUL DIFFERENCES REPORT")
    w.print("=" * 110)
    w.print("\nShowing only differences that exceed significance thresholds.")

    impactful_events = []

    for analysis in analyses:
        minute = analysis.game.timestamp / 1000 / 60

        # Team-level stat differences
        for stat in stats:
            threshold = IMPACTFUL_THRESHOLDS.get(stat, 0)
            metric = analysis.team_comparisons.comparisons[stat]["vs_opponent_team"]
            diff = metric["difference"]

            if abs(diff) >= threshold:
                impactful_events.append({
                    "minute": minute,
                    "type": "team",
                    "context": "Blue vs Red",
                    "stat": stat,
                    "difference": diff,
                    "value": metric["value"],
                    "reference": metric["reference"],
                })

        # Objective differences
        for objective in OBJECTIVE_NAMES:
            threshold = IMPACTFUL_OBJECTIVE_THRESHOLDS.get(objective, 1)
            metric = analysis.team_comparisons.objective_comparisons[objective]
            diff = metric["difference"]

            if abs(diff) >= threshold:
                impactful_events.append({
                    "minute": minute,
                    "type": "objective",
                    "context": "Blue vs Red",
                    "stat": objective,
                    "difference": diff,
                    "value": metric["value"],
                    "reference": metric["reference"],
                })

        # Player-level differences (vs lane opponent)
        for player_analysis in analysis.players:
            player = player_analysis.player
            opponent = player_analysis.opponent

            for stat in stats:
                threshold = IMPACTFUL_THRESHOLDS.get(stat, 0)
                metric = player_analysis.comparisons[stat]["vs_opponent"]
                diff = metric["difference"]

                if abs(diff) >= threshold:
                    impactful_events.append({
                        "minute": minute,
                        "type": "player",
                        "context": f"{player.champion} vs {opponent.champion} ({player.lane})",
                        "stat": stat,
                        "difference": diff,
                        "value": metric["value"],
                        "reference": metric["reference"],
                    })

        # Lane-level differences
        for lane_name, lane_analysis in analysis.lanes.items():
            own_player = lane_analysis.own_lane.players[0]
            enemy_player = lane_analysis.opponent_lane.players[0]

            for stat in stats:
                threshold = IMPACTFUL_THRESHOLDS.get(stat, 0)
                metric = lane_analysis.comparisons[stat]["vs_opponent_lane"]["total"]
                diff = metric["difference"]

                if abs(diff) >= threshold:
                    impactful_events.append({
                        "minute": minute,
                        "type": "lane",
                        "context": f"{lane_name} lane ({own_player.champion} vs {enemy_player.champion})",
                        "stat": stat,
                        "difference": diff,
                        "value": metric["value"],
                        "reference": metric["reference"],
                    })

    # Group by time
    events_by_time = {}
    for event in impactful_events:
        minute = event["minute"]
        if minute not in events_by_time:
            events_by_time[minute] = []
        events_by_time[minute].append(event)

    # Print grouped events
    for minute in sorted(events_by_time.keys()):
        events = events_by_time[minute]
        w.print(f"\n@ {minute:.0f} min")
        w.print("  " + "-" * 100)

        # Group by type for cleaner output
        team_events = [e for e in events if e["type"] == "team"]
        objective_events = [e for e in events if e["type"] == "objective"]
        player_events = [e for e in events if e["type"] == "player"]
        lane_events = [e for e in events if e["type"] == "lane"]

        if team_events:
            w.print("  TEAM:")
            for e in team_events:
                w.print(
                    f"    {e['stat']:<20} "
                    f"{e['value']:>8.0f} vs {e['reference']:>8.0f} "
                    f"(diff: {e['difference']:>+8.0f})"
                )

        if objective_events:
            w.print("  OBJECTIVES:")
            for e in objective_events:
                w.print(
                    f"    {e['stat']:<20} "
                    f"{e['value']:>8.0f} vs {e['reference']:>8.0f} "
                    f"(diff: {e['difference']:>+8.0f})"
                )

        if lane_events:
            # Group lane events by lane
            lanes_seen = {}
            for e in lane_events:
                if e["context"] not in lanes_seen:
                    lanes_seen[e["context"]] = []
                lanes_seen[e["context"]].append(e)

            w.print("  LANES:")
            for context, lane_list in lanes_seen.items():
                w.print(f"    {context}:")
                for e in lane_list:
                    w.print(
                        f"      {e['stat']:<18} "
                        f"{e['value']:>8.0f} vs {e['reference']:>8.0f} "
                        f"(diff: {e['difference']:>+8.0f})"
                    )

        if player_events:
            # Group player events by matchup
            players_seen = {}
            for e in player_events:
                if e["context"] not in players_seen:
                    players_seen[e["context"]] = []
                players_seen[e["context"]].append(e)

            w.print("  PLAYERS:")
            for context, player_list in players_seen.items():
                w.print(f"    {context}:")
                for e in player_list:
                    w.print(
                        f"      {e['stat']:<18} "
                        f"{e['value']:>8.0f} vs {e['reference']:>8.0f} "
                        f"(diff: {e['difference']:>+8.0f})"
                    )

    # Summary of most impactful moments
    w.print("\n" + "-" * 110)
    w.print("SUMMARY: MOST IMPACTFUL MOMENTS")
    w.print("-" * 110)

    # Find peak advantages for key stats
    key_stats = ["gold", "xp", "cs"]

    for stat in key_stats:
        stat_events = [e for e in impactful_events if e["stat"] == stat and e["type"] == "team"]
        if stat_events:
            peak_event = max(stat_events, key=lambda e: abs(e["difference"]))
            w.print(
                f"  Peak {stat} diff: {peak_event['difference']:>+.0f} "
                f"@ {peak_event['minute']:.0f} min"
            )

    # Objective control summary
    w.print("\n  Objective control:")
    for objective in ["dragons", "barons", "heralds", "grubs", "turrets"]:
        obj_events = [e for e in impactful_events if e["stat"] == objective]
        if obj_events:
            final_event = obj_events[-1]
            w.print(
                f"    {objective:<16} "
                f"Blue: {final_event['value']:.0f}, "
                f"Red: {final_event['reference']:.0f} "
                f"(final diff: {final_event['difference']:>+.0f})"
            )


def print_team_timeline_tables(analyses, w: Writer):
    """Prints total team stats across timestamps in chunked 10-minute blocks with aligned columns."""
    w.print("\n" + "=" * 95)
    w.print("TEAM STATS TIMELINE (TOTALS & AVERAGES)")
    w.print("=" * 95)

    CHUNK_SIZE = 10
    total_frames = len(analyses)

    for team_id in [100, 200]:
        w.print(f"\n--- TEAM {team_id} TOTALS ---")
        for start_idx in range(0, total_frames, CHUNK_SIZE):
            chunk = analyses[start_idx:start_idx + CHUNK_SIZE]
            timestamps = [a.game.timestamp / 1000 / 60 for a in chunk]

            # Standardized 8-character width per column
            header = f"  {'Stat':<12}" + "".join([f"{f'{int(ts)}m':>8}" for ts in timestamps])
            w.print("\n" + header)
            w.print("  " + "-" * (12 + 8 * len(timestamps)))

            for stat in ["gold", "xp", "cs", "kills", "deaths", "assists"]:
                row = f"  {stat:<12}"
                for a in chunk:
                    t_snap = a.teams[team_id]
                    val = getattr(t_snap, stat, 0)
                    row += f"{val:>8.0f}"
                w.print(row)


def print_final_report(analyses, w: Writer, stats=None):
    """Print a summary report aggregated over the full timeline."""
    if stats is None:
        stats = REPORT_STATS

    if not analyses:
        w.print("\nNo analyses to summarize.")
        return

    first = analyses[0]
    last = analyses[-1]

    game_start_min = first.game.timestamp / 1000 / 60
    game_end_min = last.game.timestamp / 1000 / 60

    w.print("\n" + "=" * 110)
    w.print(
        f"FINAL MATCH SUMMARY"
        f"  ({game_start_min:.1f} min – {game_end_min:.1f} min,"
        f"  {len(analyses)} sample(s))"
    )
    w.print("=" * 110)

    # ------------------------------------------------------------------
    # Player extremes summary (best/worst at each stat)
    # ------------------------------------------------------------------
    print_player_extremes(last, w, stats)

    # ------------------------------------------------------------------
    # Stat spectrum (players ranked from best to worst per stat)
    # ------------------------------------------------------------------
    print_stat_spectrum(last, w, stats)

    # ------------------------------------------------------------------
    # Team summary
    # ------------------------------------------------------------------

    team = first.team_comparisons
    w.print(
        f"\nTEAM ADVANTAGE SUMMARY"
        f" ({team_label(team.own_team.team)} vs {team_label(team.opponent_team.team)})"
    )
    w.print("  " + "-" * 100)
    w.print(
        f"  {'stat':<24}"
        f"  {'avg diff':>13}"
        f"   {'peak diff':>13}   {'@ min':>5}"
        f"   {'final diff':>13}   {'@ min':>5}"
    )
    w.print("  " + "-" * 100)

    for stat in stats:
        series = _collect_stat_series(
            analyses,
            lambda a, s=stat: a.team_comparisons.comparisons[s]["vs_opponent_team"]["difference"],
        )
        summary = _summarize_series(series)
        _print_summary_row(stat, summary, w)

    # ------------------------------------------------------------------
    # Objective summary
    # ------------------------------------------------------------------
    w.print("\nOBJECTIVE ADVANTAGE SUMMARY")
    w.print("  " + "-" * 100)
    w.print(
        f"  {'objective':<24}"
        f"  {'avg diff':>13}"
        f"   {'peak diff':>13}   {'@ min':>5}"
        f"   {'final diff':>13}   {'@ min':>5}"
    )
    w.print("  " + "-" * 100)

    for objective in OBJECTIVE_NAMES:
        series = _collect_stat_series(
            analyses,
            lambda a, o=objective: a.team_comparisons.objective_comparisons[o]["difference"],
        )
        summary = _summarize_series(series)
        _print_summary_row(objective, summary, w)

    # ------------------------------------------------------------------
    # Lane summary
    # ------------------------------------------------------------------
    lane_order = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

    w.print("\nLANE ADVANTAGE SUMMARY (own lane total vs opponent lane total)")
    w.print("  " + "-" * 100)

    for lane_name in lane_order:
        sample_analysis = next(
            (a for a in analyses if lane_name in a.lanes),
            None,
        )

        if sample_analysis is None:
            continue

        sample_lane = sample_analysis.lanes[lane_name]
        own_champ = sample_lane.own_lane.players[0].champion
        enemy_champ = sample_lane.opponent_lane.players[0].champion

        w.print(
            f"\n  {lane_name:<8}"
            f" {own_champ:<14} vs {enemy_champ}"
        )
        w.print(
            f"    {'stat':<24}"
            f"  {'avg diff':>13}"
            f"   {'peak diff':>13}   {'@ min':>5}"
            f"   {'final diff':>13}   {'@ min':>5}"
        )

        for stat in stats:
            series = _collect_stat_series(
                analyses,
                lambda a, s=stat, ln=lane_name: (
                    a.lanes[ln].comparisons[s]["vs_opponent_lane"]["total"]["difference"]
                    if ln in a.lanes
                    else None
                ),
            )
            summary = _summarize_series(series)
            _print_summary_row(stat, summary, w, indent="    ")

    # ------------------------------------------------------------------
    # Player summary
    # ------------------------------------------------------------------
    w.print("\nPLAYER ADVANTAGE SUMMARY (vs lane opponent)")
    w.print("  " + "-" * 100)

    sorted_players = sorted(
        first.players,
        key=lambda pa: pa.player.participant_id,
    )

    for pa in sorted_players:
        pid = pa.player.participant_id
        player_champ = pa.player.champion
        opponent_champ = pa.opponent.champion
        lane = pa.player.lane

        w.print(
            f"\n  [{pid:>2}]"
            f" {player_champ:<14} vs {opponent_champ:<14}"
            f" ({lane})"
        )
        w.print(
            f"    {'stat':<24}"
            f"  {'avg diff':>13}"
            f"   {'peak diff':>13}   {'@ min':>5}"
            f"   {'final diff':>13}   {'@ min':>5}"
        )

        for stat in stats:
            series = _collect_stat_series(
                analyses,
                lambda a, s=stat, p=pid: next(
                    (
                        pa2.comparisons[s]["vs_opponent"]["difference"]
                        for pa2 in a.players
                        if pa2.player.participant_id == p
                    ),
                    None,
                ),
            )
            summary = _summarize_series(series)
            _print_summary_row(stat, summary, w, indent="    ")

    w.print("\n" + "=" * 110)
    w.print("END OF REPORT")
    w.print("=" * 110)


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def create_snapshot(frame, player_info, kda_stats=None):
    participant_id = player_info["participant_id"]
    player = frame["participantFrames"][str(participant_id)]

    cs = player["minionsKilled"] + player["jungleMinionsKilled"]
    stats = player["championStats"]
    timestamp = frame["timestamp"]
    gold = player["totalGold"]

    minutes = (timestamp / 1000) / 60
    gold_per_minute = gold / minutes if minutes > 0 else 0.0
    cs_per_minute = cs / minutes if minutes > 0 else 0.0

    default_stats = {
        "kills": 0, "deaths": 0, "assists": 0,
        "wards_placed": 0, "wards_killed": 0, "vision_score": 0.0
    }
    pkda = kda_stats.get(participant_id, default_stats) if kda_stats else default_stats

    kills = pkda.get("kills", 0)
    deaths = pkda.get("deaths", 0)
    assists = pkda.get("assists", 0)
    kda = (kills + assists) / max(1, deaths)

    damage_stats = player.get("damageStats", {})
    total_damage = damage_stats.get(
        "totalDamageDoneToChampions",
        player_info.get("total_damage", 0)
    )

    return PlayerSnapshot(
        participant_id=participant_id,
        timestamp=timestamp,
        name=player_info["name"],
        tag=player_info["tag"],
        champion=player_info["champion"],
        team=player_info["team"],
        lane=player_info["lane"],
        role=player_info["role"],
        level=player["level"],
        xp=player["xp"],
        gold=gold,
        cs=cs,
        kills=kills,
        deaths=deaths,
        assists=assists,
        kda=kda,
        gold_per_minute=gold_per_minute,
        cs_per_minute=cs_per_minute,
        attack_damage=stats["attackDamage"],
        ability_power=stats["abilityPower"],
        health=stats["health"],
        max_health=stats["healthMax"],
        armor=stats["armor"],
        magic_resist=stats["magicResist"],
        attack_speed=stats["attackSpeed"],
        movement_speed=stats["movementSpeed"],
        ability_haste=stats["abilityHaste"],
        armor_pen=stats["armorPen"],
        armor_pen_percent=stats["armorPenPercent"],
        magic_pen=stats["magicPen"],
        magic_pen_percent=stats["magicPenPercent"],
        health_regen=stats["healthRegen"],
        lifesteal=stats["lifesteal"],
        omnivamp=stats["omnivamp"],
        total_damage=total_damage,
        vision_score=pkda.get("vision_score", 0.0),
        wards_placed=pkda.get("wards_placed", 0),
        wards_killed=pkda.get("wards_killed", 0),
    )


def create_snapshots(frame, players, kda_stats=None):
    return [
        create_snapshot(frame, player_info, kda_stats)
        for player_info in ordered_player_infos(players)
    ]

def extract_objectives_from_events(events, up_to_timestamp):
    """Extract objective counts from timeline events up to a given timestamp."""
    objectives = {
        100: TeamObjectiveSnapshot(),
        200: TeamObjectiveSnapshot(),
    }

    for event in events:
        if event["timestamp"] > up_to_timestamp:
            break

        event_type = event.get("type")

        if event_type == "BUILDING_KILL":
            team = 100 if event.get("teamId") == 200 else 200  # Team that killed gets credit
            building_type = event.get("buildingType")
            tower_type = event.get("towerType", "")

            if building_type == "TOWER_BUILDING":
                objectives[team].turrets += 1
                if tower_type == "OUTER_TURRET":
                    objectives[team].outer_turrets += 1
                elif tower_type == "INNER_TURRET":
                    objectives[team].inner_turrets += 1
                elif tower_type == "BASE_TURRET":
                    objectives[team].inhibitor_turrets += 1
                elif tower_type == "NEXUS_TURRET":
                    objectives[team].nexus_turrets += 1
            elif building_type == "INHIBITOR_BUILDING":
                objectives[team].inhibitors += 1

        elif event_type == "ELITE_MONSTER_KILL":
            team = event.get("killerTeamId", 0)
            monster_type = event.get("monsterType")
            monster_subtype = event.get("monsterSubType", "")

            if team in objectives:
                if monster_type == "DRAGON":
                    objectives[team].dragons += 1
                    if monster_subtype in ["FIRE_DRAGON", "WATER_DRAGON", "EARTH_DRAGON", "AIR_DRAGON", "HEXTECH_DRAGON", "CHEMTECH_DRAGON"]:
                        objectives[team].elemental_drakes += 1
                elif monster_type == "RIFTHERALD":
                    objectives[team].heralds += 1
                elif monster_type == "BARON_NASHOR":
                    objectives[team].barons += 1
                elif monster_type == "HORDE":
                    objectives[team].grubs += 1

    return objectives


def compute_frame_advanced_metrics(snapshots):
    teams = {100: [p for p in snapshots if p.team == 100], 200: [p for p in snapshots if p.team == 200]}
    for team_id, team_players in teams.items():
        team_kills = max(1, sum(p.kills for p in team_players))
        team_gold = max(1, sum(p.gold for p in team_players))
        team_dmg = max(1.0, sum(p.total_damage for p in team_players))

        for p in team_players:
            p.kp_pct = ((p.kills + p.assists) / team_kills) * 100.0
            p.gold_share = (p.gold / team_gold) * 100.0
            p.dmg_share = (p.total_damage / team_dmg) * 100.0
            p.gold_efficiency = (p.dmg_share / max(0.01, p.gold_share)) if p.gold_share > 0 else 0.0


def analyze_timeline(frames, players, interval_seconds=60, all_events=None, perspective_team=100):
    analyses = []
    interval_ms = interval_seconds * 1000
    max_timestamp = frames[-1]["timestamp"]
    timestamp = interval_ms

    if all_events is None:
        all_events = []
        for frame in frames:
            all_events.extend(frame.get("events", []))

    while timestamp <= max_timestamp:
        frame = get_closest_frame(frames, timestamp)
        kda_stats = extract_kda_from_events(all_events, timestamp)
        snapshots = create_snapshots(frame, players, kda_stats)
        compute_frame_advanced_metrics(snapshots)
        objectives = extract_objectives_from_events(all_events, timestamp)
        analysis = build_match_analysis(snapshots, objectives, perspective_team=perspective_team)
        analyses.append(analysis)
        timestamp += interval_ms

    return analyses


def print_frame(frame, players):
    timestamp = frame["timestamp"] / 1000

    print(f"\n=== {timestamp:.0f}s ===")

    for participant_id, player in frame["participantFrames"].items():
        participant_id = int(participant_id)

        info = players[participant_id]

        cs = (
            player["minionsKilled"]
            + player["jungleMinionsKilled"]
        )

        print(
            f"{info['name']:20} "
            f"{info['champion']:12} "
            f"Team={team_label(info['team'])} "
            f"Level={player['level']:2} "
            f"XP={player['xp']:5} "
            f"Gold={player['totalGold']:5} "
            f"CS={cs:3}"
        )


def get_closest_frame(frames, timestamp_ms):
    return min(
        frames,
        key=lambda frame: abs(frame["timestamp"] - timestamp_ms)
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def print_main_advantage_report(analysis, w: Writer, stats=None):
    """Prints team and objective per-interval advantages for the main report."""
    if stats is None:
        stats = REPORT_STATS

    minute = analysis.game.timestamp / 1000 / 60

    w.print("\n" + "=" * 110)
    w.print(f"MATCH ADVANTAGE @ {minute:5.1f} min")
    w.print("=" * 110)

    team = analysis.team_comparisons
    team_score = calculate_team_advantage_score(team)

    w.print(
        f"\nTEAM ADVANTAGE "
        f"({team_label(team.own_team.team)} vs "
        f"{team_label(team.opponent_team.team)})"
    )

    w.print(
        f"  Advantage Score: {team_score:+.1f} / 100"
        f"  | {advantage_label(team_score)}"
    )

    w.print(
        "  Score interpretation: "
        "-100 = strong Red | 0 = even | +100 = strong Blue"
    )
    w.print("  " + "-" * 100)
    for stat in stats:
        metric = team.comparisons[stat]["vs_opponent_team"]
        w.print(f"  {stat:<24} {format_metric(metric)}")

    w.print("\nOBJECTIVE ADVANTAGE")
    w.print("  " + "-" * 100)
    for objective in OBJECTIVE_NAMES:
        metric = team.objective_comparisons[objective]
        w.print(f"  {objective:<24} {format_metric(metric)}")


# ---------------------------------------------------------------------------
# Advantage Score Evolution & Rankings
# ---------------------------------------------------------------------------

def _get_player_analysis(analysis, participant_id):
    return next(
        (
            pa for pa in analysis.players
            if pa.player.participant_id == participant_id
        ),
        None,
    )


def _get_final_player_scores(analysis):
    """
    Return the contextual final player scores used by the final rankings.

    The three scores intentionally use different comparison populations:

        lane_score = player vs other players in the same lane
        team_score = player vs other players on the same team
        game_score = player vs every other player in the game

    The original lane-opponent Advantage Score remains available through
    calculate_player_advantage_score() for the normal player analysis.
    """
    return calculate_contextual_player_scores(analysis)


def print_advantage_score_evolution(analyses, w: Writer):
    """
    Prints a compact data-point table showing how team, lane and champion
    advantage evolved at every timestamp.
    """
    if not analyses:
        return

    w.print("\n" + "=" * 110)
    w.print("ADVANTAGE SCORE EVOLUTION")
    w.print("=" * 110)

    w.print(
        "\nScore scale: -100 = strong Red advantage | "
        "0 = even | +100 = strong Blue advantage"
    )
    w.print(
        "Champion scores are relative to the champion's lane opponent. "
        "Team and lane scores are Blue-centric."
    )

    # ------------------------------------------------------------------
    # Team evolution
    # ------------------------------------------------------------------
    w.print("\nTEAM ADVANTAGE SCORE EVOLUTION")
    w.print("  " + "-" * 110)

    times = [
        a.game.timestamp / 1000 / 60
        for a in analyses
    ]

    w.print(
        "  "
        + f"{'':<18}"
        + "".join(f"{minute:>10.1f}m" for minute in times)
    )

    w.print("  " + "-" * 110)

    w.print(
        "  "
        + f"{'Blue Advantage':<18}"
        + "".join(
            f"{calculate_team_advantage_score(a.team_comparisons):>+10.1f}"
            for a in analyses
        )
    )

    w.print("  " + "-" * 110)

    # ------------------------------------------------------------------
    # Lane evolution
    # ------------------------------------------------------------------
    w.print("\nLANE ADVANTAGE SCORE EVOLUTION")
    w.print("  " + "-" * 110)

    w.print(
        "  "
        + f"{'Lane':<12}"
        + "".join(f"{minute:>10.1f}m" for minute in times)
    )

    w.print("  " + "-" * 110)

    for lane_name in LANE_ORDER:
        values = []

        for a in analyses:
            lane = a.lanes.get(lane_name)

            if lane is None:
                values.append(None)
            else:
                values.append(
                    calculate_lane_advantage_score(lane)
                )

        w.print(
            "  "
            + f"{lane_name:<12}"
            + "".join(
                f"{score:>+10.1f}" if score is not None else f"{'N/A':>10}"
                for score in values
            )
        )

    w.print("  " + "-" * 110)

    # ------------------------------------------------------------------
    # Champion evolution
    # ------------------------------------------------------------------
    w.print("\nCHAMPION ADVANTAGE SCORE EVOLUTION")
    w.print("  " + "-" * 110)

    w.print(
        "  "
        + f"{'Champion':<16}"
          f"{'Team':<7}"
          f"{'Lane':<9}"
        + "".join(f"{minute:>10.1f}m" for minute in times)
    )

    w.print("  " + "-" * 110)

    final_order = sorted(
        analyses[-1].players,
        key=lambda pa: (
            0 if pa.player.team == REPORT_BLUE_TEAM else 1,
            LANE_ORDER.index(pa.player.lane)
            if pa.player.lane in LANE_ORDER else 99,
        ),
    )

    for final_pa in final_order:
        final_player = final_pa.player

        scores = []

        for a in analyses:
            pa = _get_player_analysis(
                a,
                final_player.participant_id,
            )

            if pa is None:
                scores.append(None)
            else:
                scores.append(
                    calculate_player_advantage_score(pa)
                )

        w.print(
            "  "
            + f"{final_player.champion:<16}"
              f"{team_label(final_player.team):<7}"
              f"{final_player.lane:<9}"
            + "".join(
                f"{score:>+10.1f}" if score is not None
                else f"{'N/A':>10}"
                for score in scores
            )
        )

    w.print("  " + "-" * 110)


def print_final_advantage_rankings(analysis, w: Writer):
    """
    Prints final contextual player rankings.

    Each ranking uses a different comparison population:

        Lane:
            player vs every other player in that lane

        Team:
            player vs every other player on that team

        Game:
            player vs every other player in the game
    """
    player_scores = _get_final_player_scores(analysis)

    # ---------------------------------------------------------------
    # Build contextual rankings
    # ---------------------------------------------------------------

    lane_rankings = {}
    team_rankings = {}
    game_ranked = sorted(
        player_scores.values(),
        key=lambda item: item["game_score"],
        reverse=True,
    )

    for lane_name in LANE_ORDER:
        lane_items = [
            item
            for item in player_scores.values()
            if item["player_analysis"].player.lane == lane_name
        ]

        lane_rankings[lane_name] = sorted(
            lane_items,
            key=lambda item: item["lane_score"],
            reverse=True,
        )

    blue_players = sorted(
        [
            item
            for item in player_scores.values()
            if item["player_analysis"].player.team == REPORT_BLUE_TEAM
        ],
        key=lambda item: item["team_score"],
        reverse=True,
    )

    red_team_id = 200 if REPORT_BLUE_TEAM == 100 else 100

    red_players = sorted(
        [
            item
            for item in player_scores.values()
            if item["player_analysis"].player.team == red_team_id
        ],
        key=lambda item: item["team_score"],
        reverse=True,
    )

    team_rankings["Blue"] = blue_players
    team_rankings["Red"] = red_players

    # ---------------------------------------------------------------
    # Overall game ranks
    # ---------------------------------------------------------------

    overall_rank = {
        item["player_analysis"].player.participant_id: rank
        for rank, item in enumerate(game_ranked, start=1)
    }

    # ---------------------------------------------------------------
    # Team ranks
    # ---------------------------------------------------------------

    team_rank = {}

    for rank, item in enumerate(blue_players, start=1):
        team_rank[
            item["player_analysis"].player.participant_id
        ] = rank

    for rank, item in enumerate(red_players, start=1):
        team_rank[
            item["player_analysis"].player.participant_id
        ] = rank

    # ---------------------------------------------------------------
    # Header
    # ---------------------------------------------------------------

    w.print("\n" + "=" * 110)
    w.print("FINAL ADVANTAGE RANKINGS")
    w.print("=" * 110)

    w.print(
        "\nRanking scores are contextual pairwise Advantage Scores."
    )
    w.print(
        "Each score compares the player against every other player "
        "in the relevant comparison pool."
    )
    w.print(
        "Lane = same lane | Team = same team | Game = all other players."
    )
    w.print(
        "Each pairwise stat difference is normalized using the existing "
        "Advantage Score thresholds before aggregation."
    )

    # ---------------------------------------------------------------
    # Complete game ranking
    # ---------------------------------------------------------------

    w.print("\nFINAL PLAYER GAME RANKING")
    w.print("  " + "-" * 110)
    w.print(
        f"  {'Rank':>5}  "
        f"{'Team':<6}  "
        f"{'Lane':<9}  "
        f"{'Champion':<16}  "
        f"{'Player':<24}  "
        f"{'Game Score':>11}"
    )
    w.print("  " + "-" * 110)

    for item in game_ranked:
        player = item["player_analysis"].player

        w.print(
            f"  #{overall_rank[player.participant_id]:>4}  "
            f"{team_label(player.team):<6}  "
            f"{player.lane:<9}  "
            f"{player.champion:<16}  "
            f"{(player.name + '#' + player.tag):<24}  "
            f"{item['game_score']:+11.1f}"
        )

    # ---------------------------------------------------------------
    # Best / Worst Player of Each Lane
    # ---------------------------------------------------------------

    w.print("\nBEST / WORST PLAYER OF EACH LANE")
    w.print("  " + "-" * 110)

    for lane_name in LANE_ORDER:
        lane_items = lane_rankings[lane_name]

        if not lane_items:
            continue

        best = lane_items[0]
        worst = lane_items[-1]

        best_p = best["player_analysis"].player
        worst_p = worst["player_analysis"].player

        w.print(f"\n  {lane_name}:")

        w.print(
            f"    BEST:  {best_p.champion:<16} "
            f"({best_p.name}#{best_p.tag}) "
            f"[{team_label(best_p.team)}] "
            f"Lane Score {best['lane_score']:+.1f}"
        )

        w.print(
            f"    WORST: {worst_p.champion:<16} "
            f"({worst_p.name}#{worst_p.tag}) "
            f"[{team_label(worst_p.team)}] "
            f"Lane Score {worst['lane_score']:+.1f}"
        )

    # ---------------------------------------------------------------
    # Best / Worst Player of Each Team
    # ---------------------------------------------------------------

    w.print("\nBEST / WORST PLAYER OF EACH TEAM")
    w.print("  " + "-" * 110)

    for team_name in ("Blue", "Red"):
        team_items = team_rankings[team_name]

        if not team_items:
            continue

        best = team_items[0]
        worst = team_items[-1]

        best_p = best["player_analysis"].player
        worst_p = worst["player_analysis"].player

        w.print(f"\n  {team_name}:")

        w.print(
            f"    BEST:  {best_p.champion:<16} "
            f"({best_p.name}#{best_p.tag}) "
            f"Team Score {best['team_score']:+.1f}"
        )

        w.print(
            f"    WORST: {worst_p.champion:<16} "
            f"({worst_p.name}#{worst_p.tag}) "
            f"Team Score {worst['team_score']:+.1f}"
        )

    # ---------------------------------------------------------------
    # Best / Worst Player of Entire Game
    # ---------------------------------------------------------------

    if game_ranked:
        best = game_ranked[0]
        worst = game_ranked[-1]

        best_p = best["player_analysis"].player
        worst_p = worst["player_analysis"].player

        w.print("\nBEST / WORST PLAYER OF THE ENTIRE GAME")
        w.print("  " + "-" * 110)

        w.print(
            f"  BEST:  {best_p.champion:<16} "
            f"({best_p.name}#{best_p.tag}) "
            f"[{team_label(best_p.team)} / {best_p.lane}] "
            f"Game Score {best['game_score']:+.1f}"
        )

        w.print(
            f"  WORST: {worst_p.champion:<16} "
            f"({worst_p.name}#{worst_p.tag}) "
            f"[{team_label(worst_p.team)} / {worst_p.lane}] "
            f"Game Score {worst['game_score']:+.1f}"
        )

    # ---------------------------------------------------------------
    # All contextual scores
    # ---------------------------------------------------------------

    w.print("\nCONTEXTUAL PLAYER ADVANTAGE SCORES")
    w.print("  " + "-" * 110)
    w.print(
        f"  {'Team':<6}  "
        f"{'Lane':<9}  "
        f"{'Champion':<16}  "
        f"{'Player':<24}  "
        f"{'Lane':>11}  "
        f"{'Team':>11}  "
        f"{'Game':>11}"
    )
    w.print("  " + "-" * 110)

    ordered = sorted(
        player_scores.values(),
        key=lambda item: (
            0
            if item["player_analysis"].player.team == REPORT_BLUE_TEAM
            else 1,
            LANE_ORDER.index(item["player_analysis"].player.lane)
            if item["player_analysis"].player.lane in LANE_ORDER
            else 99,
        ),
    )

    for item in ordered:
        player = item["player_analysis"].player

        w.print(
            f"  {team_label(player.team):<6}  "
            f"{player.lane:<9}  "
            f"{player.champion:<16}  "
            f"{(player.name + '#' + player.tag):<24}  "
            f"{item['lane_score']:>+11.1f}  "
            f"{item['team_score']:>+11.1f}  "
            f"{item['game_score']:>+11.1f}"
        )


def print_main_final_report(analyses, w: Writer, stats=None):
    """Prints general team and objective summaries across the whole game for the main report."""
    if stats is None:
        stats = REPORT_STATS

    if not analyses:
        return

    first = analyses[0]
    last = analyses[-1]
    game_start_min = first.game.timestamp / 1000 / 60
    game_end_min = last.game.timestamp / 1000 / 60

    w.print("\n" + "=" * 110)
    w.print(f"FINAL MATCH SUMMARY ({game_start_min:.1f} min – {game_end_min:.1f} min)")
    w.print("=" * 110)

    team = first.team_comparisons
    w.print(f"\nTEAM ADVANTAGE SUMMARY ({team_label(team.own_team.team)} vs {team_label(team.opponent_team.team)})")
    w.print("  " + "-" * 100)
    w.print(f"  {'stat':<24}  {'avg diff':>13}   {'peak diff':>13}   {'@ min':>5}   {'final diff':>13}   {'@ min':>5}")
    w.print("  " + "-" * 100)

    for stat in stats:
        series = _collect_stat_series(
            analyses,
            lambda a, s=stat: a.team_comparisons.comparisons[s]["vs_opponent_team"]["difference"],
        )
        summary = _summarize_series(series)
        _print_summary_row(stat, summary, w)

    w.print("\nOBJECTIVE ADVANTAGE SUMMARY")
    w.print("  " + "-" * 100)
    w.print(f"  {'objective':<24}  {'avg diff':>13}   {'peak diff':>13}   {'@ min':>5}   {'final diff':>13}   {'@ min':>5}")
    w.print("  " + "-" * 100)

    for objective in OBJECTIVE_NAMES:
        series = _collect_stat_series(
            analyses,
            lambda a, o=objective: a.team_comparisons.objective_comparisons[o]["difference"],
        )
        summary = _summarize_series(series)
        _print_summary_row(objective, summary, w)


def _get_objective_deltas(prev_objs: TeamObjectiveSnapshot, curr_objs: TeamObjectiveSnapshot) -> list[str]:
    """Calculate objective increases between two snapshots."""
    deltas = []
    for obj_name in OBJECTIVE_NAMES:
        prev_val = getattr(prev_objs, obj_name, 0)
        curr_val = getattr(curr_objs, obj_name, 0)
        diff = curr_val - prev_val
        if diff > 0:
            formatted_name = obj_name.replace("_", " ").title()
            deltas.append(f"{diff}x {formatted_name}")
    return deltas


def write_swings_report(report_analyses, output_dir):
    """Generates game_swings.txt tracking gold, XP, kills (teamfights), and objective kills."""
    filename = os.path.join(output_dir, "game_swings.txt")

    with Writer(filename) as w:
        w.print("=" * 80)
        w.print("GAME SWINGS & MOMENTUM SHIFTS")
        w.print("=" * 80)
        w.print("  (Tracking Gold/XP shifts >= 1,500, Teamfights >= 3 Kills, or Objective Takes)\n")

        swings_found = 0

        for i in range(1, len(report_analyses)):
            prev = report_analyses[i - 1]
            curr = report_analyses[i]

            prev_time = prev.game.timestamp / 1000 / 60
            curr_time = curr.game.timestamp / 1000 / 60

            # Resource Shifts
            prev_gold_diff = prev.teams[100].gold - prev.teams[200].gold
            curr_gold_diff = curr.teams[100].gold - curr.teams[200].gold
            gold_swing = curr_gold_diff - prev_gold_diff

            prev_xp_diff = prev.teams[100].xp - prev.teams[200].xp
            curr_xp_diff = curr.teams[100].xp - curr.teams[200].xp
            xp_swing = curr_xp_diff - prev_xp_diff

            # Combat / Kill Deltas (Teamfights)
            t100_kills = curr.teams[100].kills - prev.teams[100].kills
            t200_kills = curr.teams[200].kills - prev.teams[200].kills
            total_interval_kills = t100_kills + t200_kills

            # Objective Deltas (Pushes & Neutral Objectives)
            t100_objs = _get_objective_deltas(prev.teams[100].objectives, curr.teams[100].objectives)
            t200_objs = _get_objective_deltas(prev.teams[200].objectives, curr.teams[200].objectives)
            has_objectives = bool(t100_objs or t200_objs)

            # Swing conditions: Big economic shift, multi-kill teamfight, or objective capture with gold movement
            if (
                abs(gold_swing) >= 1500
                or abs(xp_swing) >= 1500
                or total_interval_kills >= 3
                or (has_objectives and abs(gold_swing) >= 800)
            ):
                swings_found += 1
                favored_team = 100 if gold_swing >= 0 else 200

                w.print(f"[{prev_time:.0f}m -> {curr_time:.0f}m] MOMENTUM SWING")
                w.print(f"  Favored Team: {team_label(favored_team)}")
                w.print(f"  Gold Swing:   {gold_swing:+7.0f} (Net Diff: {curr_gold_diff:+7.0f})")
                w.print(f"  XP Swing:     {xp_swing:+7.0f} (Net Diff: {curr_xp_diff:+7.0f})")
                w.print(f"  Teamfights:   Blue (+{t100_kills if REPORT_BLUE_TEAM == 100 else t200_kills} kills) vs Red (+{t200_kills if REPORT_BLUE_TEAM == 100 else t100_kills} kills)")

                if t100_objs:
                    w.print(f"  {team_label(100)} Objectives: {', '.join(t100_objs)}")
                if t200_objs:
                    w.print(f"  {team_label(200)} Objectives: {', '.join(t200_objs)}")
                w.print("")

        if swings_found == 0:
            w.print("  No major swings or key teamfights detected in interval checks.")


def write_economy_report(report_analyses, players, output_dir):
    """Generates economy_spikes.txt breaking down gold & CS rates by game phase."""
    filename = os.path.join(output_dir, "economy_spikes.txt")

    with Writer(filename) as w:
        w.print("=" * 85)
        w.print("ECONOMY & CS EFFICIENCY REPORT BY GAME PHASE")
        w.print("=" * 85)

        phases = {
            "Laning Phase (0-10m)": [a for a in report_analyses if (a.game.timestamp / 1000 / 60) <= 10],
            "Mid Game (10-20m)": [a for a in report_analyses if 10 < (a.game.timestamp / 1000 / 60) <= 20],
            "Late Game (20m+)": [a for a in report_analyses if (a.game.timestamp / 1000 / 60) > 20],
        }

        for phase_name, frames in phases.items():
            if not frames:
                continue

            first_f, last_f = frames[0], frames[-1]
            start_m = first_f.game.timestamp / 1000 / 60
            end_m = last_f.game.timestamp / 1000 / 60
            duration = max(1.0, end_m - start_m)

            w.print(f"\n--- {phase_name} ({start_m:.0f}m - {end_m:.0f}m) ---")
            w.print(f"  {'ID':>2}  {'Champion':<14}  {'Gold Earned':>12}  {'Gold/Min':>10}  {'CS Gained':>10}  {'CS/Min':>8}")
            w.print("  " + "-" * 70)

            for pid, player_info in sorted(players.items()):
                p_start = next(p for p in first_f.game.players if p.participant_id == pid)
                p_end = next(p for p in last_f.game.players if p.participant_id == pid)

                gold_gained = p_end.gold - p_start.gold
                cs_gained = p_end.cs - p_start.cs

                gpm = gold_gained / duration
                cspm = cs_gained / duration

                w.print(
                    f"  {pid:>2}  {player_info['champion']:<14}  "
                    f"{gold_gained:>12.0f}  {gpm:>10.1f}  "
                    f"{cs_gained:>10.0f}  {cspm:>8.1f}"
                )


def write_objectives_report(all_events, output_dir):
    """Generates objectives_timeline.txt logging macro objectives chronologically."""
    filename = os.path.join(output_dir, "objectives_timeline.txt")

    objective_types = {"ELITE_MONSTER_KILL", "BUILDING_KILL", "TURRET_PLATE_DESTROYED"}

    obj_events = [e for e in all_events if e.get("type") in objective_types]
    obj_events.sort(key=lambda x: x.get("timestamp", 0))

    with Writer(filename) as w:
        w.print("=" * 80)
        w.print("OBJECTIVES CHRONOLOGICAL TIMELINE")
        w.print("=" * 80)
        w.print(f"  {'Time':<8}  {'Event Type':<24}  {'Detail / Subtype':<20}  {'Team':<6}")
        w.print("  " + "-" * 72)

        for e in obj_events:
            ts_min = e.get("timestamp", 0) / 1000 / 60
            etype = e.get("type", "")

            if etype == "ELITE_MONSTER_KILL":
                detail = e.get("monsterType", "MONSTER")
                if "monsterSubType" in e:
                    detail += f" ({e['monsterSubType']})"
                team = e.get("killerTeamId", "N/A")
            elif etype == "BUILDING_KILL":
                detail = f"{e.get('buildingType', 'BUILDING')} ({e.get('laneType', '')})"
                team = e.get("teamId", "N/A")
            else:
                detail = f"Plate ({e.get('laneType', '')})"
                team = e.get("teamId", "N/A")

            w.print(f"  {ts_min:5.1f}m   {etype:<24}  {detail:<20}  {team_label(team) if isinstance(team, int) and team in (100, 200) else team}")


def write_match_summary_markdown(final_analysis, report_analyses, players, output_dir):
    """Write a comprehensive Markdown summary using the runner's team as Blue."""
    filepath = os.path.join(output_dir, "match_summary.md")
    game_duration_min = final_analysis.game.timestamp / 1000 / 60

    blue_final = final_analysis.teams[REPORT_BLUE_TEAM]
    red_team_id = 200 if REPORT_BLUE_TEAM == 100 else 100
    red_final = final_analysis.teams[red_team_id]
    ordered_players = ordered_snapshots(final_analysis.game.players)

    def pct(value):
        return f"{value:.1f}%"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Match Analysis Summary\n\n")
        f.write(f"**Game Duration:** {game_duration_min:.1f} minutes  \n")
        if REPORT_RUNNER_PARTICIPANT_ID is not None:
            runner = next((p for p in ordered_players if p.participant_id == REPORT_RUNNER_PARTICIPANT_ID), None)
            if runner:
                f.write(f"**Script Runner:** {runner.name}#{runner.tag} — {runner.champion} ({runner.lane})  \n")
        f.write(
            f"**Final Score:** Blue ({blue_final.kills} Kills, {blue_final.gold:,} Gold) "
            f"vs Red ({red_final.kills} Kills, {red_final.gold:,} Gold)\n\n"
        )

        f.write("## Team Overview\n\n")
        f.write("| Team | Kills | Deaths | Assists | Gold | XP | CS | Damage | Vision | Turrets | Inhibitors | Dragons | Heralds | Barons | Grubs |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for label, team in (("Blue", blue_final), ("Red", red_final)):
            o = team.objectives
            f.write(
                f"| {label} | {team.kills} | {team.deaths} | {team.assists} | "
                f"{team.gold:,} | {team.xp:,} | {team.cs:,} | {team.total_damage:,.0f} | "
                f"{team.vision_score:.0f} | {o.turrets} | {o.inhibitors} | {o.dragons} | "
                f"{o.heralds} | {o.barons} | {o.grubs} |\n"
            )
        f.write("\n")

        f.write("## Final Roster & Player Performance\n\n")
        f.write("| ID | Team | Lane | Champion | Player | Level | Gold | XP | CS | K/D/A | KP% | Gold Share | Dmg Share | Gold Eff | Vision | Wards Placed | Wards Cleared |\n")
        f.write("|---:|---|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|\n")
        for p in ordered_players:
            adv = calculate_advanced_metrics(p, final_analysis.teams[p.team])
            runner_mark = " **(Runner)**" if p.participant_id == REPORT_RUNNER_PARTICIPANT_ID else ""
            f.write(
                f"| {p.participant_id} | **{team_label(p.team)}** | {p.lane or '-'} | **{p.champion}** | "
                f"{p.name}#{p.tag}{runner_mark} | {p.level} | {p.gold:,} | {p.xp:,} | {p.cs} | "
                f"{p.kills}/{p.deaths}/{p.assists} | {pct(adv['kp_pct'])} | {pct(adv['gold_share'])} | "
                f"{pct(adv['dmg_share'])} | {adv['gold_eff']:.2f}x | {adv['vision_score']:.0f} | "
                f"{adv['wards_placed']:.0f} | {adv['wards_killed']:.0f} |\n"
            )
        f.write("\n")

        f.write("## Objective Control\n\n")
        f.write("| Objective | Blue | Red | Difference (Blue - Red) |\n")
        f.write("|---|---:|---:|---:|\n")
        blue_o, red_o = blue_final.objectives, red_final.objectives
        objective_pairs = [
            ("Turrets", blue_o.turrets, red_o.turrets),
            ("Outer Turrets", blue_o.outer_turrets, red_o.outer_turrets),
            ("Inner Turrets", blue_o.inner_turrets, red_o.inner_turrets),
            ("Inhibitor Turrets", blue_o.inhibitor_turrets, red_o.inhibitor_turrets),
            ("Nexus Turrets", blue_o.nexus_turrets, red_o.nexus_turrets),
            ("Inhibitors", blue_o.inhibitors, red_o.inhibitors),
            ("Dragons", blue_o.dragons, red_o.dragons),
            ("Elemental Drakes", blue_o.elemental_drakes, red_o.elemental_drakes),
            ("Rift Heralds", blue_o.heralds, red_o.heralds),
            ("Barons", blue_o.barons, red_o.barons),
            ("Void Grubs", blue_o.grubs, red_o.grubs),
        ]
        for label, b, r in objective_pairs:
            f.write(f"| {label} | {b} | {r} | {b-r:+d} |\n")
        if blue_o.dragon_soul or red_o.dragon_soul:
            f.write(f"| Dragon Soul | {blue_o.dragon_soul or 'None'} | {red_o.dragon_soul or 'None'} | — |\n")
        f.write("\n")

        f.write("## Final Lane Matchups\n\n")
        f.write("| Lane | Blue Player | Blue Champion | Red Player | Red Champion | Gold Diff | XP Diff | CS Diff | K/D/A Diff |\n")
        f.write("|---|---|---|---|---|---:|---:|---:|---|\n")
        for lane_name in LANE_ORDER:
            lane_snap = final_analysis.lanes.get(lane_name)
            if not lane_snap:
                continue
            blue_p = lane_snap.own_lane.players[0]
            red_p = lane_snap.opponent_lane.players[0]
            f.write(
                f"| {lane_name} | {blue_p.name} | {blue_p.champion} | {red_p.name} | {red_p.champion} | "
                f"{blue_p.gold-red_p.gold:+,.0f} | {blue_p.xp-red_p.xp:+,.0f} | {blue_p.cs-red_p.cs:+d} | "
                f"{blue_p.kills-red_p.kills:+d}/{red_p.deaths-blue_p.deaths:+d}/{blue_p.assists-red_p.assists:+d} |\n"
            )
        f.write("\n")

        f.write("## Major Game Swings & Momentum\n\n")
        f.write("| Window | Favored | Gold Swing | XP Swing | Kills (Blue - Red) | Objectives Secured |\n")
        f.write("|---|---|---:|---:|---:|---|\n")
        swing_count = 0
        for i in range(1, len(report_analyses)):
            prev, curr = report_analyses[i - 1], report_analyses[i]
            prev_time = prev.game.timestamp / 1000 / 60
            curr_time = curr.game.timestamp / 1000 / 60
            gold_swing = (curr.teams[REPORT_BLUE_TEAM].gold - curr.teams[red_team_id].gold) - (prev.teams[REPORT_BLUE_TEAM].gold - prev.teams[red_team_id].gold)
            xp_swing = (curr.teams[REPORT_BLUE_TEAM].xp - curr.teams[red_team_id].xp) - (prev.teams[REPORT_BLUE_TEAM].xp - prev.teams[red_team_id].xp)
            blue_k = curr.teams[REPORT_BLUE_TEAM].kills - prev.teams[REPORT_BLUE_TEAM].kills
            red_k = curr.teams[red_team_id].kills - prev.teams[red_team_id].kills
            blue_objs = _get_objective_deltas(prev.teams[REPORT_BLUE_TEAM].objectives, curr.teams[REPORT_BLUE_TEAM].objectives)
            red_objs = _get_objective_deltas(prev.teams[red_team_id].objectives, curr.teams[red_team_id].objectives)
            if abs(gold_swing) >= 1500 or abs(xp_swing) >= 1500 or (blue_k + red_k) >= 3 or blue_objs or red_objs:
                swing_count += 1
                favored = "Blue" if gold_swing >= 0 else "Red"
                objectives = []
                if blue_objs:
                    objectives.append(f"Blue: {', '.join(blue_objs)}")
                if red_objs:
                    objectives.append(f"Red: {', '.join(red_objs)}")
                f.write(
                    f"| {prev_time:.0f}m - {curr_time:.0f}m | {favored} | {gold_swing:+,.0f} | {xp_swing:+,.0f} | "
                    f"{blue_k} - {red_k} | {'; '.join(objectives) or 'None'} |\n"
                )
        if swing_count == 0:
            f.write("| N/A | N/A | 0 | 0 | 0 - 0 | No major swings detected |\n")
        f.write("\n")

        f.write("## Advantage Timeline\n\n")
        f.write("Net differences are always **Blue - Red**. Positive values favor the script runner's team.\n\n")
        f.write("| Time | Gold Diff | XP Diff | CS Diff | Kill Diff | Turret Diff | Dragon Diff | Baron Diff | Herald Diff | Grub Diff |\n")
        f.write("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for a in report_analyses:
            b, r = a.teams[REPORT_BLUE_TEAM], a.teams[red_team_id]
            bo, ro = b.objectives, r.objectives
            minute = a.game.timestamp / 1000 / 60
            f.write(
                f"| {minute:.0f}m | {b.gold-r.gold:+,.0f} | {b.xp-r.xp:+,.0f} | {b.cs-r.cs:+d} | "
                f"{b.kills-r.kills:+d} | {bo.turrets-ro.turrets:+d} | {bo.dragons-ro.dragons:+d} | "
                f"{bo.barons-ro.barons:+d} | {bo.heralds-ro.heralds:+d} | {bo.grubs-ro.grubs:+d} |\n"
            )
        f.write("\n")

        # ================================================================
        # Advantage Score Evolution
        # ================================================================
        f.write("## Advantage Score Evolution\n\n")

        f.write(
            "Advantage Scores are normalized to a **-100 to +100 scale**. "
            "For teams and lanes, positive values mean Blue advantage. "
            "For champions, positive values mean that champion is ahead "
            "of their lane opponent.\n\n"
        )

        # ---------------------------------------------------------------
        # Team score evolution
        # ---------------------------------------------------------------
        f.write("### Team Advantage Score Evolution\n\n")

        f.write(
            "Positive values indicate Blue advantage; "
            "negative values indicate Red advantage.\n\n"
        )

        # Timestamps are columns so the evolution can be read horizontally.
        team_times = [
            a.game.timestamp / 1000 / 60
            for a in report_analyses
        ]

        f.write("| | " + " | ".join(
            f"{minute:.1f}m"
            for minute in team_times
        ) + " |\n")

        f.write("|---|" + "|".join(
            "---:"
            for _ in team_times
        ) + "|\n")

        f.write("| **Team Advantage** | " + " | ".join(
            f"**{calculate_team_advantage_score(a.team_comparisons):+.1f}**"
            for a in report_analyses
        ) + " |\n")

        f.write("\n")

        # ---------------------------------------------------------------
        # Lane score evolution
        # ---------------------------------------------------------------
        f.write("### Lane Advantage Score Evolution\n\n")

        f.write(
            "Positive values indicate Blue advantage; "
            "negative values indicate Red advantage.\n\n"
        )

        lane_times = [
            a.game.timestamp / 1000 / 60
            for a in report_analyses
        ]

        f.write("| Lane | " + " | ".join(
            f"{minute:.1f}m"
            for minute in lane_times
        ) + " |\n")

        f.write("|---|" + "|".join(
            "---:"
            for _ in lane_times
        ) + "|\n")

        for lane_name in LANE_ORDER:
            values = []

            for a in report_analyses:
                lane = a.lanes.get(lane_name)

                if lane is None:
                    values.append("N/A")
                else:
                    score = calculate_lane_advantage_score(lane)
                    values.append(f"{score:+.1f}")

            f.write(
                f"| **{lane_name}** | "
                + " | ".join(values)
                + " |\n"
            )

        f.write("\n")

        # ---------------------------------------------------------------
        # Champion score evolution
        # ---------------------------------------------------------------
        f.write("### Champion Advantage Score Evolution\n\n")

        f.write(
            "Positive values indicate that the champion is ahead of "
            "their lane opponent; negative values indicate that they are behind.\n\n"
        )

        champion_times = [
            a.game.timestamp / 1000 / 60
            for a in report_analyses
        ]

        # Use the final roster to establish a stable row for every champion.
        final_analysis_for_order = report_analyses[-1]

        ordered_final_players = sorted(
            final_analysis_for_order.players,
            key=lambda pa: (
                0 if pa.player.team == REPORT_BLUE_TEAM else 1,
                LANE_ORDER.index(pa.player.lane)
                if pa.player.lane in LANE_ORDER else 99,
            ),
        )

        f.write(
            "| Champion | Team | Lane | "
            + " | ".join(
                f"{minute:.1f}m"
                for minute in champion_times
            )
            + " |\n"
        )

        f.write(
            "|---|---|---|"
            + "|".join("---:" for _ in champion_times)
            + "|\n"
        )

        for final_pa in ordered_final_players:
            final_player = final_pa.player

            values = []

            for a in report_analyses:
                pa = _get_player_analysis(
                    a,
                    final_player.participant_id,
                )

                if pa is None:
                    values.append("N/A")
                else:
                    score = calculate_player_advantage_score(pa)
                    values.append(f"{score:+.1f}")

            f.write(
                f"| **{final_player.champion}** | "
                f"{team_label(final_player.team)} | "
                f"{final_player.lane} | "
                + " | ".join(values)
                + " |\n"
            )

        f.write("\n")

        # ================================================================
        # Final Advantage Rankings
        # ================================================================
        f.write("## Final Advantage Rankings\n\n")

        f.write(
            "Champion Advantage Score measures how far ahead or behind "
            "each champion finished relative to their lane opponent.\n\n"
        )

        final_scores = _get_final_player_scores(final_analysis)

        ranked = sorted(
            final_scores.values(),
            key=lambda item: item["game_score"],
            reverse=True,
        )

        blue_players = sorted(
            [
                item
                for item in final_scores.values()
                if item["player_analysis"].player.team == REPORT_BLUE_TEAM
            ],
            key=lambda item: item["team_score"],
            reverse=True,
        )

        red_players = sorted(
            [
                item
                for item in final_scores.values()
                if item["player_analysis"].player.team != REPORT_BLUE_TEAM
            ],
            key=lambda item: item["team_score"],
            reverse=True,
        )

        overall_rank = {
            item["player_analysis"].player.participant_id: rank
            for rank, item in enumerate(ranked, start=1)
        }

        team_rank = {}

        for rank, item in enumerate(blue_players, start=1):
            team_rank[
                item["player_analysis"].player.participant_id
            ] = rank

        for rank, item in enumerate(red_players, start=1):
            team_rank[
                item["player_analysis"].player.participant_id
            ] = rank

        # ---------------------------------------------------------------
        # Every champion
        # ---------------------------------------------------------------
        f.write("### Final Contextual Player Advantage Scores\n\n")
        f.write(
            "| Game Rank | Team Rank | Team | Lane | Champion | Player | Lane Score | Team Score | Game Score |\n"
        )
        f.write(
            "|---:|---:|---|---|---|---|---:|---:|---:|\n"
        )

        for item in ranked:
            pa = item["player_analysis"]
            p = pa.player

            f.write(
                f"| #{overall_rank[p.participant_id]} | "
                f"#{team_rank[p.participant_id]} | "
                f"{team_label(p.team)} | "
                f"{p.lane} | "
                f"**{p.champion}** | "
                f"{p.name}#{p.tag} | "
                f"{item['lane_score']:+.1f} | "
                f"{item['team_score']:+.1f} | "
                f"**{item['game_score']:+.1f}** |\n"
            )

        f.write("\n")

        # ---------------------------------------------------------------
        # Best / Worst Champion of Each Lane
        # ---------------------------------------------------------------
        f.write("### Best / Worst Player of Each Lane\n\n")

        f.write(
            "| Lane | Best Player | Lane Score | Worst Player | Lane Score |\n"
        )
        f.write(
            "|---|---|---:|---|---:|\n"
        )

        for lane_name in LANE_ORDER:
            lane_players = [
                item
                for item in final_scores.values()
                if item["player_analysis"].player.lane == lane_name
            ]

            if not lane_players:
                continue

            lane_players.sort(
                key=lambda item: item["lane_score"],
                reverse=True,
            )

            best = lane_players[0]
            worst = lane_players[-1]

            best_p = best["player_analysis"].player
            worst_p = worst["player_analysis"].player

            f.write(
                f"| {lane_name} | "
                f"**{best_p.champion}** ({team_label(best_p.team)}) | "
                f"{best['lane_score']:+.1f} | "
                f"**{worst_p.champion}** ({team_label(worst_p.team)}) | "
                f"{worst['lane_score']:+.1f} |\n"
            )

        f.write("\n")

        # ---------------------------------------------------------------
        # Best / Worst Player of Each Team
        # ---------------------------------------------------------------
        f.write("### Best / Worst Player of Each Team\n\n")

        f.write(
            "| Team | Best Player | Team Score | Worst Player | Team Score |\n"
        )
        f.write(
            "|---|---|---:|---|---:|\n"
        )

        for team_name, team_items in (
                ("Blue", blue_players),
                ("Red", red_players),
        ):
            if not team_items:
                continue

            best = team_items[0]
            worst = team_items[-1]

            best_p = best["player_analysis"].player
            worst_p = worst["player_analysis"].player

            f.write(
                f"| {team_name} | "
                f"**{best_p.champion}** ({best_p.name}) | "
                f"{best['team_score']:+.1f} | "
                f"**{worst_p.champion}** ({worst_p.name}) | "
                f"{worst['team_score']:+.1f} |\n"
            )

        f.write("\n")

        # ---------------------------------------------------------------
        # Best / Worst of entire game
        # ---------------------------------------------------------------
        best = ranked[0]
        worst = ranked[-1]

        best_p = best["player_analysis"].player
        worst_p = worst["player_analysis"].player

        f.write("### Best / Worst Player of the Entire Game\n\n")

        f.write(
            f"- **BEST:** **{best_p.champion}** "
            f"({best_p.name}#{best_p.tag}, "
            f"{team_label(best_p.team)} {best_p.lane}) — "
            f"Game Advantage Score **{best['game_score']:+.1f}**.\n"
        )

        f.write(
            f"- **WORST:** **{worst_p.champion}** "
            f"({worst_p.name}#{worst_p.tag}, "
            f"{team_label(worst_p.team)} {worst_p.lane}) — "
            f"Game Advantage Score **{worst['game_score']:+.1f}**.\n"
        )

        f.write("\n")

        f.write("## Performance Highlights\n\n")
        highest_dmg = max(ordered_players, key=lambda p: p.total_damage)
        highest_eff = max(ordered_players, key=lambda p: calculate_advanced_metrics(p, final_analysis.teams[p.team])['gold_eff'])
        highest_vision = max(ordered_players, key=lambda p: p.vision_score)
        highest_gold = max(ordered_players, key=lambda p: p.gold)
        highest_kp = max(ordered_players, key=lambda p: calculate_advanced_metrics(p, final_analysis.teams[p.team])['kp_pct'])
        f.write(f"- **Damage Leader:** {highest_dmg.champion} ({highest_dmg.name}) — {highest_dmg.total_damage:,.0f} champion damage.\n")
        f.write(f"- **Gold Leader:** {highest_gold.champion} ({highest_gold.name}) — {highest_gold.gold:,} gold.\n")
        f.write(f"- **Highest Kill Participation:** {highest_kp.champion} ({highest_kp.name}) — {calculate_advanced_metrics(highest_kp, final_analysis.teams[highest_kp.team])['kp_pct']:.1f}%.\n")
        f.write(f"- **Most Resource Efficient:** {highest_eff.champion} ({highest_eff.name}) — {calculate_advanced_metrics(highest_eff, final_analysis.teams[highest_eff.team])['gold_eff']:.2f}x gold efficiency.\n")
        f.write(f"- **Vision Leader:** {highest_vision.champion} ({highest_vision.name}) — {highest_vision.vision_score:.0f} vision score, {highest_vision.wards_placed} wards placed, {highest_vision.wards_killed} cleared.\n")

    return filepath

def calculate_advanced_metrics(player_snap, team_snap):
    """Calculates KP%, Damage Share, Gold Share, Gold Efficiency, and Vision metrics for a player snapshot."""
    kills = getattr(player_snap, "kills", 0)
    assists = getattr(player_snap, "assists", 0)
    player_gold = getattr(player_snap, "gold", 0)
    player_dmg = getattr(player_snap, "total_damage",
                         getattr(player_snap, "magic_damage", 0) + getattr(player_snap, "physical_damage", 0))

    team_kills = getattr(team_snap, "kills", 0)
    team_gold = getattr(team_snap, "gold", 0)
    team_dmg = getattr(team_snap, "total_damage", 0)

    # 1. Kill Participation %
    kp_pct = ((kills + assists) / max(1, team_kills)) * 100.0

    # 2. Gold Share %
    gold_share = (player_gold / max(1, team_gold)) * 100.0

    # 3. Damage Share %
    dmg_share = (player_dmg / max(1, team_dmg)) * 100.0 if team_dmg > 0 else 0.0

    # 4. Gold Efficiency Ratio (Damage Share / Gold Share)
    gold_eff = (dmg_share / max(0.01, gold_share)) if gold_share > 0 else 0.0

    # 5. Vision Metrics
    vision_score = getattr(player_snap, "vision_score", 0)
    wards_placed = getattr(player_snap, "wards_placed", 0)
    wards_killed = getattr(player_snap, "wards_killed", 0)

    return {
        "kp_pct": kp_pct,
        "gold_share": gold_share,
        "dmg_share": dmg_share,
        "gold_eff": gold_eff,
        "vision_score": vision_score,
        "wards_placed": wards_placed,
        "wards_killed": wards_killed,
    }


def get_closest_analysis(report_analyses, target_minute, max_diff_minutes=1.5):
    """Finds the analysis frame closest to target_minute within tolerance."""
    if not report_analyses:
        return None
    closest = min(
        report_analyses,
        key=lambda a: abs((a.game.timestamp / 1000 / 60) - target_minute)
    )
    if abs((closest.game.timestamp / 1000 / 60) - target_minute) <= max_diff_minutes:
        return closest
    return None


def write_player_report(player_info, report_analyses, final_analysis, output_dir, stats=None):
    """Generates individual player report including KP%, Gold Efficiency, Damage Share, and Vision Pressure."""
    if stats is None:
        stats = REPORT_STATS

    pid = player_info["participant_id"]
    champ = player_info["champion"]
    name = player_info["name"]

    safe_champ = "".join(c for c in champ if c.isalnum() or c in ("_", "-"))
    safe_name = "".join(c for c in name if c.isalnum() or c in ("_", "-"))
    filename = os.path.join(output_dir, f"{safe_champ}_{safe_name}.txt")

    with Writer(filename) as w:
        w.print("=" * 80)
        w.print(f"PLAYER REPORT: {champ} ({name})")
        w.print(f"Team: {team_label(player_info['team'])} | Position: {player_info['lane']}")
        w.print("=" * 80)

        # Final Advanced Metrics
        final_p_snap = next(p for p in final_analysis.game.players if p.participant_id == pid)
        final_t_snap = final_analysis.teams[player_info["team"]]
        adv = calculate_advanced_metrics(final_p_snap, final_t_snap)

        w.print(f"\nCOMBAT & EFFICIENCY METRICS (MATCH END):")
        w.print(f"  K/D/A:                  {final_p_snap.kills} / {final_p_snap.deaths} / {final_p_snap.assists}")
        w.print(f"  Kill Participation:     {adv['kp_pct']:.1f}%")
        w.print(f"  Damage Share:           {adv['dmg_share']:.1f}%")
        w.print(f"  Gold Share:             {adv['gold_share']:.1f}%")
        w.print(f"  Gold Efficiency Ratio:  {adv['gold_eff']:.2f}x (Dmg Share / Gold Share)")

        w.print(f"\nVISION & MAP PRESSURE (MATCH END):")
        w.print(f"  Vision Score:           {adv['vision_score']:.0f}")
        w.print(f"  Wards Placed:           {adv['wards_placed']:.0f}")
        w.print(f"  Wards Cleared:          {adv['wards_killed']:.0f}")

        # Best / Worst Stats
        best_map = {p.participant_id: [] for p in final_analysis.game.players}
        worst_map = {p.participant_id: [] for p in final_analysis.game.players}

        for stat in stats:
            res = get_stat_extremes(final_analysis.game.players, stat)
            if not res or res[0] is None:
                continue
            (best_val, best_players), (worst_val, worst_players) = res
            for p in best_players:
                best_map[p.participant_id].append(f"{stat} ({best_val:.0f})")
            for p in worst_players:
                worst_map[p.participant_id].append(f"{stat} ({worst_val:.0f})")

        b_str = ", ".join(best_map[pid]) if best_map[pid] else "(none)"
        w_str = ", ".join(worst_map[pid]) if worst_map[pid] else "(none)"

        w.print(f"\nBEST/WORST AT FINAL SNAPSHOT:")
        w.print(f"  BEST at:  {b_str}")
        w.print(f"  WORST at: {w_str}\n")

        # Phase-Based Deltas
        w.print("-" * 80)
        w.print("PHASE-BASED STAT DELTAS VS OPPONENT")
        w.print("-" * 80)

        phase_snapshots = {
            "Laning Phase (10m)": get_closest_analysis(report_analyses, 10),
            "Mid Game (20m)": get_closest_analysis(report_analyses, 20),
            "Late Game (Final)": final_analysis,
        }

        w.print(f"  {'Stat':<18} {'Laning (10m)':>16} {'Mid (20m)':>16} {'Final':>16}")
        w.print("  " + "-" * 70)

        for stat in stats:
            row = f"  {stat:<18}"
            for phase_name, snap in phase_snapshots.items():
                if snap:
                    pa = next((p for p in snap.players if p.player.participant_id == pid), None)
                    diff = pa.comparisons[stat]["vs_opponent"]["difference"] if pa else 0.0
                    row += f" {diff:>+15.0f}"
                else:
                    row += f" {'N/A':>16}"
            w.print(row)

        # Per-Interval Advantage vs Opponent
        w.print("\n" + "-" * 80)
        w.print("INTERVAL ADVANTAGES (VS LANE OPPONENT)")
        w.print("-" * 80)

        for analysis in report_analyses:
            minute = analysis.game.timestamp / 1000 / 60
            pa = next((p for p in analysis.players if p.player.participant_id == pid), None)
            if pa:
                w.print(f"\n@ {minute:5.1f} min vs {pa.opponent.champion}:")
                for stat in stats:
                    metric = pa.comparisons[stat]["vs_opponent"]
                    w.print(f"  {stat:<22} {format_metric(metric)}")


def write_lane_report(lane_name, report_analyses, output_dir, stats=None):
    """Generates lane report including combined lane vision score and efficiency metrics."""
    if stats is None:
        stats = REPORT_STATS

    filename = os.path.join(output_dir, f"Lane_{lane_name}.txt")
    final_analysis = report_analyses[-1]

    with Writer(filename) as w:
        w.print("=" * 80)
        w.print(f"LANE REPORT: {lane_name}")
        w.print("=" * 80)

        # Lane Vision & Efficiency Overview at final snapshot
        lane_snap = final_analysis.lanes.get(lane_name)
        if lane_snap:
            own_p = lane_snap.own_lane.players[0]
            enemy_p = lane_snap.opponent_lane.players[0]

            own_team_snap = final_analysis.teams[own_p.team]
            enemy_team_snap = final_analysis.teams[enemy_p.team]

            own_adv = calculate_advanced_metrics(own_p, own_team_snap)
            enemy_adv = calculate_advanced_metrics(enemy_p, enemy_team_snap)

            w.print(f"\nLANE ADVANCED METRICS COMPARISON (MATCH END):")
            w.print(f"  {'Metric':<24} {own_p.champion:>15} vs {enemy_p.champion:<15} {'Diff':>10}")
            w.print("  " + "-" * 68)
            w.print(f"  {'Kill Participation':<24} {own_adv['kp_pct']:>14.1f}% vs {enemy_adv['kp_pct']:<14.1f}% {own_adv['kp_pct'] - enemy_adv['kp_pct']:>+9.1f}%")
            w.print(f"  {'Damage Share':<24} {own_adv['dmg_share']:>14.1f}% vs {enemy_adv['dmg_share']:<14.1f}% {own_adv['dmg_share'] - enemy_adv['dmg_share']:>+9.1f}%")
            w.print(f"  {'Gold Efficiency Ratio':<24} {own_adv['gold_eff']:>15.2f} vs {enemy_adv['gold_eff']:<15.2f} {own_adv['gold_eff'] - enemy_adv['gold_eff']:>+10.2f}")
            w.print(f"  {'Vision Score':<24} {own_adv['vision_score']:>15.0f} vs {enemy_adv['vision_score']:<15.0f} {own_adv['vision_score'] - enemy_adv['vision_score']:>+10.0f}")
            w.print(f"  {'Wards Placed':<24} {own_adv['wards_placed']:>15.0f} vs {enemy_adv['wards_placed']:<15.0f} {own_adv['wards_placed'] - enemy_adv['wards_placed']:>+10.0f}")

        # Per-Interval Lane Totals vs Opponent
        w.print("\n" + "-" * 80)
        w.print("INTERVAL ADVANTAGES (OWN LANE TOTAL VS OPPONENT LANE TOTAL)")
        w.print("-" * 80)

        for analysis in report_analyses:
            minute = analysis.game.timestamp / 1000 / 60
            lane = analysis.lanes.get(lane_name)
            if not lane:
                continue
            own_player = lane.own_lane.players[0]
            enemy_player = lane.opponent_lane.players[0]

            w.print(f"\n@ {minute:5.1f} min ({own_player.champion} vs {enemy_player.champion}):")
            for stat in stats:
                metric = lane.comparisons[stat]["vs_opponent_lane"]["total"]
                w.print(f"  {stat:<22} {format_metric(metric)}")


def enrich_analysis_frame(analysis):
    """Calculates advanced metrics on player models and injects player/lane comparison dicts for any timestamp frame."""
    for team_id in [100, 200]:
        t_snap = analysis.teams[team_id]
        team_players = [p for p in analysis.game.players if p.team == team_id]

        team_dmg = sum(
            getattr(p, "total_damage", 0) for p in team_players
        )

        for p in team_players:
            p_gold = getattr(p, "gold", 0)
            p_kills = getattr(p, "kills", 0)
            p_assists = getattr(p, "assists", 0)
            p_dmg = getattr(p, "total_damage", 0)

            p.kp_pct = ((p_kills + p_assists) / max(1, t_snap.kills)) * 100.0
            p.gold_share = (p_gold / max(1, t_snap.gold)) * 100.0
            p.dmg_share = (p_dmg / max(1, team_dmg)) * 100.0 if team_dmg > 0 else 0.0
            p.gold_efficiency = (p.dmg_share / max(0.01, p.gold_share)) if p.gold_share > 0 else 0.0

    # Inject comparisons into Player analyses
    for pa in analysis.players:
        p1 = pa.player
        p2 = pa.opponent
        for stat in ADVANCED_STAT_KEYS:
            val1 = getattr(p1, stat, 0.0)
            val2 = getattr(p2, stat, 0.0) if p2 else 0.0
            diff = val1 - val2
            ratio = (val1 / val2) if (val2 and val2 != 0) else None

            pa.comparisons[stat] = {
                "vs_opponent": {
                    "value": val1,
                    "reference": val2,
                    "difference": diff,
                    "ratio": ratio
                }
            }

    # Inject comparisons into Lane analyses
    for lane_name, lane_analysis in analysis.lanes.items():
        own_lane = lane_analysis.own_lane
        opp_lane = lane_analysis.opponent_lane

        for stat in ADVANCED_STAT_KEYS:
            val1 = getattr(own_lane, stat, 0.0)
            val2 = getattr(opp_lane, stat, 0.0)
            diff = val1 - val2
            ratio = (val1 / val2) if (val2 and val2 != 0) else None

            lane_analysis.comparisons[stat] = {
                "vs_opponent_lane": {
                    "total": {
                        "value": val1,
                        "reference": val2,
                        "difference": diff,
                        "ratio": ratio
                    }
                }
            }


def compare_champions_at_timestamp(analysis, champion_a, champion_b):
    """Compares any two champions in the game at a specific timestamp frame across all base and advanced stats."""
    p_a = next((p for p in analysis.game.players if p.champion.lower() == champion_a.lower()), None)
    p_b = next((p for p in analysis.game.players if p.champion.lower() == champion_b.lower()), None)

    if not p_a or not p_b:
        return f"One or both champions ({champion_a}, {champion_b}) not found in frame."

    minute = analysis.game.timestamp / 1000 / 60
    all_stats = REPORT_STATS + ADVANCED_STAT_KEYS
    comparison_results = {}

    for stat in all_stats:
        val_a = getattr(p_a, stat, 0.0)
        val_b = getattr(p_b, stat, 0.0)
        diff = val_a - val_b
        ratio = (val_a / val_b) if val_b != 0 else None

        comparison_results[stat] = {
            "value": val_a,
            "reference": val_b,
            "difference": diff,
            "ratio": ratio
        }

    return {
        "minute": minute,
        "champion_a": p_a.champion,
        "champion_b": p_b.champion,
        "comparisons": comparison_results
    }


def main():
    account = get_account_by_riot_id("døinB ryze hack", "EUNE")
    puuid = account["puuid"]
    match_ids = get_match_ids(puuid, count=20)
    match_id = match_ids[0]

    print(f"Analyzing: {match_id}")

    match = get_match(match_id)
    timeline = get_timeline(match_id)

    game_duration_sec = match["info"]["gameDuration"]
    print(f"Game duration: {game_duration_sec} seconds")

    frames = timeline["info"]["frames"]
    participants = match["info"]["participants"]

    players = {}
    runner_name = account.get("gameName") or account.get("riotIdGameName")
    runner_tag = account.get("tagLine") or account.get("riotIdTagline")
    runner_participant_id = None

    for player in participants:
        participant_id = player["participantId"]
        players[participant_id] = {
            "participant_id": participant_id,
            "name": player["riotIdGameName"],
            "tag": player["riotIdTagline"],
            "champion": player["championName"],
            "team": player["teamId"],
            "lane": player["teamPosition"],
            "role": player["individualPosition"],
            "vision_score": player.get("visionScore", 0),
            "wards_placed": player.get("wardsPlaced", 0),
            "wards_killed": player.get("wardsKilled", 0),
            "total_damage": player.get("totalDamageDealtToChampions", 0),
        }

        if (
            player.get("puuid") == account.get("puuid")
            or (runner_name and player["riotIdGameName"] == runner_name
                and (not runner_tag or player["riotIdTagline"] == runner_tag))
        ):
            runner_participant_id = participant_id

    if runner_participant_id is None:
        raise RuntimeError("Could not identify the script runner in the match participants.")

    runner_team = players[runner_participant_id]["team"]
    set_report_perspective(runner_team, runner_participant_id)

    all_events = []
    for frame in frames:
        all_events.extend(frame.get("events", []))

    analyses = analyze_timeline(
        frames,
        players,
        interval_seconds=60,
        all_events=all_events,
        perspective_team=runner_team,
    )

    for analysis in analyses:
        enrich_analysis_frame(analysis)

    report_start = parse_time("1:00")
    report_end = game_duration_sec

    report_analyses = [
        a for a in analyses
        if report_start <= (a.game.timestamp / 1000) <= report_end
    ]

    final_analysis = report_analyses[-1] if report_analyses else analyses[-1]

    # Create directory structure: reports/<matchID>_<YYYYMMDD>/
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    folder_name = f"{match_id}_{date_str}"
    output_dir = os.path.join("reports", folder_name)
    os.makedirs(output_dir, exist_ok=True)

    print(f"\nGenerating reports in directory: {output_dir}")

    # Save raw Riot API responses for debugging / analysis.
    raw_api_file = os.path.join(
        output_dir,
        "raw_api_response.json",
    )

    with open(raw_api_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "match_id": match_id,
                "match": match,
                "timeline": timeline,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"Raw API response saved to: {raw_api_file}")

    # 1. Generate Stat Spectrum Report
    spectrum_file = os.path.join(output_dir, "stat_spectrum.txt")
    with Writer(spectrum_file) as w:
        w.print("\n" + "=" * 72)
        w.print("STAT SPECTRUM REPORT")
        w.print("=" * 72)
        w.print("\nPLAYERS")
        w.print("  " + "-" * 66)
        w.print(f"  {'ID':>2}  {'Champion':<14} {'Player':<22} {'Team':<6} {'Position':<10}")
        w.print("  " + "-" * 66)
        for player in ordered_player_infos(players):
            participant_id = player["participant_id"]
            w.print(
                f"  {participant_id:>2}  "
                f"{player['champion']:<14} "
                f"{player['name']:<22} "
                f"{team_label(player['team']):<6} "
                f"{player['lane']:<10}"
            )
        print_stat_spectrum(final_analysis, w)

    # 2. Generate New Specific Report Files
    write_swings_report(report_analyses, output_dir)
    write_economy_report(report_analyses, players, output_dir)
    write_objectives_report(all_events, output_dir)

    # 3. Generate Markdown March Summary
    write_match_summary_markdown(final_analysis, report_analyses, players, output_dir)

    # 4. Generate Per-Player / Per-Champion Reports
    for player_info in players.values():
        write_player_report(player_info, report_analyses, final_analysis, output_dir)

    # 5. Generate Per-Lane Reports
    lane_order = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
    for lane_name in lane_order:
        write_lane_report(lane_name, report_analyses, output_dir)

    # 6. Generate Main Summary Report
    main_report_file = os.path.join(output_dir, "main_report.txt")

    with Writer(main_report_file) as w:
        w.print("\n" + "=" * 72)
        w.print("PLAYERS ROSTER")
        w.print("=" * 72)
        w.print(
            f"  {'ID':>2}  "
            f"{'Champion':<14} "
            f"{'Player':<22} "
            f"{'Team':<6} "
            f"{'Position':<10}"
        )
        w.print("  " + "-" * 66)

        for player in ordered_player_infos(players):
            participant_id = player["participant_id"]
            w.print(
                f"  {participant_id:>2}  "
                f"{player['champion']:<14} "
                f"{player['name']:<22} "
                f"{team_label(player['team']):<6} "
                f"{player['lane']:<10}"
            )

        print_team_timeline_tables(report_analyses, w)
        print_short_average_report(report_analyses, w)
        print_impactful_differences_report(report_analyses, w)

        for analysis in report_analyses:
            print_main_advantage_report(analysis, w)

        print_main_final_report(report_analyses, w)

        # Explicit Advantage Score evolution and final rankings
        print_advantage_score_evolution(report_analyses, w)
        print_final_advantage_rankings(final_analysis, w)

    print("\nAll reports successfully created!")


if __name__ == "__main__":
    main()
