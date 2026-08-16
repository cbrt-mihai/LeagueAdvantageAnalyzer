import sys
import datetime

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

# Thresholds for "impactful" differences
IMPACTFUL_THRESHOLDS = {
    "gold": 500,
    "xp": 300,
    "cs": 10,
    "level": 1,
    "attack_damage": 20,
    "ability_power": 30,
    "health": 200,
    "max_health": 200,
    "armor": 10,
    "magic_resist": 10,
    "attack_speed": 20,
    "movement_speed": 20,
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

    if ratio is None:
        ratio_text = "N/A"
    else:
        ratio_text = f"{ratio:.2f}x"

    return (
        f"{metric['value']:>9.2f}"
        f" vs {metric['reference']:>9.2f}"
        f"   diff {metric['difference']:>+9.2f}"
        f"   {ratio_text:>7}"
    )


# ---------------------------------------------------------------------------
# Per-interval report
# ---------------------------------------------------------------------------

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
        f" (Team {team.own_team.team} vs Team {team.opponent_team.team})"
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

        own_player = lane.own_lane.players[0]
        enemy_player = lane.opponent_lane.players[0]

        w.print(
            f"\n  {lane_name:<8}"
            f" {own_player.champion:<14} vs {enemy_player.champion}"
        )

        for stat in stats:
            metric = lane.comparisons[stat]["vs_opponent_lane"]["total"]
            w.print(f"    {stat:<22} {format_metric(metric)}")

    w.print("\nPLAYER ADVANTAGE (vs lane opponent)")
    w.print("  " + "-" * 100)

    for player_analysis in sorted(
        analysis.players,
        key=lambda item: item.player.participant_id,
    ):
        player = player_analysis.player
        opponent = player_analysis.opponent

        w.print(
            f"\n  [{player.participant_id:>2}]"
            f" {player.champion:<14} vs {opponent.champion:<14}"
            f" ({player.lane})"
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

def print_player_extremes(analysis, w: Writer, stats=None):
    """For each player, print which stats they were best/worst at."""
    if stats is None:
        stats = REPORT_STATS

    players = analysis.game.players

    # Build a lookup of stat -> (best_player, worst_player)
    stat_extremes = {}
    for stat in stats:
        values = [(p, getattr(p, stat)) for p in players]
        values_sorted = sorted(values, key=lambda x: x[1], reverse=True)
        best_player = values_sorted[0][0]
        worst_player = values_sorted[-1][0]
        stat_extremes[stat] = {
            "best": best_player,
            "worst": worst_player,
            "best_value": values_sorted[0][1],
            "worst_value": values_sorted[-1][1],
        }

    w.print("\nPLAYER EXTREMES (Best/Worst at each stat)")
    w.print("  " + "-" * 100)

    # For each player, find which stats they were best/worst at
    for player in sorted(players, key=lambda p: p.participant_id):
        best_stats = []
        worst_stats = []

        for stat in stats:
            if stat_extremes[stat]["best"].participant_id == player.participant_id:
                best_stats.append(f"{stat} ({stat_extremes[stat]['best_value']:.0f})")
            if stat_extremes[stat]["worst"].participant_id == player.participant_id:
                worst_stats.append(f"{stat} ({stat_extremes[stat]['worst_value']:.0f})")

        w.print(
            f"\n  [{player.participant_id:>2}] {player.champion:<14} "
            f"(Team {player.team}, {player.lane})"
        )

        if best_stats:
            w.print(f"       BEST at:  {', '.join(best_stats)}")
        else:
            w.print(f"       BEST at:  (none)")

        if worst_stats:
            w.print(f"       WORST at: {', '.join(worst_stats)}")
        else:
            w.print(f"       WORST at: (none)")


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

        for participant_id, player in players_dict.items():
            w.print(
                f"  {participant_id:>2}  "
                f"{player['champion']:<14} "
                f"{player['name']:<22} "
                f"{player['team']:<6} "
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

        for participant_id, player in players_dict.items():
            w.print(
                f"  {participant_id:>2}  "
                f"{player['champion']:<14} "
                f"{player['name']:<22} "
                f"{player['team']:<6} "
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
    w.print("\nTEAM STAT ADVANTAGES (Team 100 vs Team 200)")
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
    w.print("\nOBJECTIVE ADVANTAGES (Team 100 vs Team 200)")
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
                    "context": f"Team 100 vs Team 200",
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
                    "context": f"Team 100 vs Team 200",
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
                f"Team 100: {final_event['value']:.0f}, "
                f"Team 200: {final_event['reference']:.0f} "
                f"(final diff: {final_event['difference']:>+.0f})"
            )


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
        f" (Team {team.own_team.team} vs Team {team.opponent_team.team})"
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

def create_snapshot(frame, player_info):
    player = frame["participantFrames"][str(player_info["participant_id"])]

    cs = (
        player["minionsKilled"]
        + player["jungleMinionsKilled"]
    )

    stats = player["championStats"]

    return PlayerSnapshot(
        participant_id=player_info["participant_id"],
        timestamp=frame["timestamp"],
        name=player_info["name"],
        tag=player_info["tag"],
        champion=player_info["champion"],
        team=player_info["team"],
        lane=player_info["lane"],
        role=player_info["role"],
        level=player["level"],
        xp=player["xp"],
        gold=player["totalGold"],
        cs=cs,

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
    )


def create_snapshots(frame, players):
    snapshots = []

    for player_info in players.values():
        snapshot = create_snapshot(frame, player_info)
        snapshots.append(snapshot)

    return snapshots

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


def analyze_timeline(frames, players, interval_seconds=60, all_events=None):
    analyses = []

    interval_ms = interval_seconds * 1000
    max_timestamp = frames[-1]["timestamp"]
    timestamp = interval_ms

    # Collect all events from frames if not provided
    if all_events is None:
        all_events = []
        for frame in frames:
            all_events.extend(frame.get("events", []))

    while timestamp <= max_timestamp:
        frame = get_closest_frame(frames, timestamp)
        snapshots = create_snapshots(frame, players)
        objectives = extract_objectives_from_events(all_events, timestamp)
        analysis = build_match_analysis(snapshots, objectives)
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
            f"Team={info['team']} "
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

def main():
    account = get_account_by_riot_id(
        "døinB ryze hack",
        "EUNE"
    )

    puuid = account["puuid"]

    match_ids = get_match_ids(puuid, count=20)

    match_id = match_ids[0]

    print(f"Analyzing: {match_id}")

    match = get_match(match_id)
    timeline = get_timeline(match_id)

    print(f"Game duration: {match['info']['gameDuration']} seconds")

    frames = timeline["info"]["frames"]

    print(f"Number of frames: {len(frames)}")

    participants = match["info"]["participants"]

    players = {}

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
        }

    # Collect all events from timeline
    all_events = []
    for frame in frames:
        all_events.extend(frame.get("events", []))

    analyses = analyze_timeline(
        frames,
        players,
        interval_seconds=60,
        all_events=all_events,
    )

    print(f"\nGenerated {len(analyses)} analyses.")

    report_start = parse_time("1:00")
    report_end = parse_time("30:00")

    report_analyses = [
        a
        for a in analyses
        if report_start <= a.game.timestamp / 1000 <= report_end
    ]

    # Build the output file name from the match ID and current time
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # Get the final analysis for extremes/spectrum reports
    final_analysis = report_analyses[-1] if report_analyses else analyses[-1]

    # ----------------------------------------------------------------
    # Report 1: Player Extremes (separate file)
    # ----------------------------------------------------------------
    extremes_filename = write_player_extremes_report(
        final_analysis, match_id, timestamp_str, players
    )
    print(f"Written: {extremes_filename}")

    # ----------------------------------------------------------------
    # Report 2: Stat Spectrum (separate file)
    # ----------------------------------------------------------------
    spectrum_filename = write_stat_spectrum_report(
        final_analysis, match_id, timestamp_str, players
    )
    print(f"Written: {spectrum_filename}")

    # ----------------------------------------------------------------
    # Report 3: Main Report (existing report)
    # ----------------------------------------------------------------
    report_filename = f"report_{match_id}_{timestamp_str}.txt"
    print(f"Writing main report to: {report_filename}\n")

    with Writer(report_filename) as w:

        # ----------------------------------------------------------------
        # Header: player roster
        # ----------------------------------------------------------------
        w.print("\n" + "=" * 72)
        w.print("PLAYERS")
        w.print("=" * 72)

        w.print(
            f"  {'ID':>2}  "
            f"{'Champion':<14} "
            f"{'Player':<22} "
            f"{'Team':<6} "
            f"{'Position':<10}"
        )

        w.print("  " + "-" * 66)

        for participant_id, player in players.items():
            w.print(
                f"  {participant_id:>2}  "
                f"{player['champion']:<14} "
                f"{player['name']:<22} "
                f"{player['team']:<6} "
                f"{player['lane']:<10}"
            )

        # ----------------------------------------------------------------
        # Short average report (new condensed format)
        # ----------------------------------------------------------------
        print_short_average_report(report_analyses, w)

        # ----------------------------------------------------------------
        # Impactful differences report (new)
        # ----------------------------------------------------------------
        print_impactful_differences_report(report_analyses, w)

        # ----------------------------------------------------------------
        # Per-interval advantage reports
        # ----------------------------------------------------------------
        for analysis in report_analyses:
            print_advantage_report(analysis, w)

        # ----------------------------------------------------------------
        # Final summary
        # ----------------------------------------------------------------
        print_final_report(report_analyses, w)

    # ----------------------------------------------------------------
    # Custom comparison (console only, not duplicated to the report file)
    # ----------------------------------------------------------------
    request = ComparisonRequest(
        source_id=4,
        target="opponent",
        stats=[
            "gold",
            "xp",
            "cs",
            "ability_power",
            "attack_damage",
        ],
        start="1:00",
        end="30:00",
    )

    results = compare_timeline(
        analyses,
        request,
    )

    print("\n" + "=" * 100)
    print("CUSTOM COMPARISON")
    print("=" * 100)

    print(
        f"\n  Source: Malzahar"
        f"\n  Target: lane opponent"
        f"\n  Time:   {request.start} - {request.end}"
        f"\n  Stats:  {', '.join(request.stats)}"
    )

    for result in results:

        minute = result.timestamp / 1000 / 60

        print(f"\n  {minute:5.1f} min")

        for stat, metric in result.stats.items():

            ratio = metric["ratio"]

            if ratio is None:
                ratio_text = "N/A"
            else:
                ratio_text = f"{ratio:.2f}x"

            print(
                f"    {stat:<20}"
                f"{metric['value']:>9.1f}"
                f" vs {metric['reference']:>9.1f}"
                f"   diff {metric['difference']:>+9.1f}"
                f"   {ratio_text:>7}"
            )


if __name__ == "__main__":
    main()
