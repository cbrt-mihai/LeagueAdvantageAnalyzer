from models import (
    PlayerSnapshot,
    TeamSnapshot,
    LaneSnapshot,
    GameSnapshot,
    PlayerAnalysis,
    LaneAnalysis,
    TeamAnalysis,
    MatchAnalysis,
    TeamObjectiveSnapshot,
    aggregate_players,
    average_players,
    aggregate_objectives,
)

from dataclasses import dataclass
from typing import Optional


STAT_NAMES = [
    "gold",
    "gold_per_minute",
    "xp",
    "cs",
    "cs_per_minute",
    "level",

    "kills",
    "deaths",
    "assists",
    "kda",

    "attack_damage",
    "ability_power",
    "health",
    "max_health",
    "armor",
    "magic_resist",
    "attack_speed",
    "movement_speed",

    "ability_haste",
    "armor_pen",
    "armor_pen_percent",
    "magic_pen",
    "magic_pen_percent",
    "health_regen",
    "lifesteal",
    "omnivamp",

    # Advanced & Vision Metrics
    "kp_pct",
    "gold_share",
    "dmg_share",
    "gold_efficiency",
    "vision_score",
    "wards_placed",
    "wards_killed"
]


OBJECTIVE_NAMES = [
    "turrets",
    "outer_turrets",
    "inner_turrets",
    "inhibitor_turrets",
    "nexus_turrets",
    "inhibitors",
    "dragons",
    "elemental_drakes",
    "heralds",
    "barons",
    "grubs",
]


PLAYER_TARGETS = {
    "player",
    "opponent",
    "own_team",
    "own_team_average",
    "own_team_excluding_self_average",
    "enemy_team",
    "enemy_team_average",
    "enemy_team_excluding_opponent_average",
    "game",
    "game_average",
}


@dataclass
class ComparisonRequest:
    stats: list[str]

    source: str
    target: str

    start_seconds: Optional[float] = None
    end_seconds: Optional[float] = None

    source_id: Optional[int] = None
    target_id: Optional[int] = None

    aggregation: str = "auto"


def validate_comparison_request(request: ComparisonRequest):
    invalid_stats = [
        stat
        for stat in request.stats
        if stat not in STAT_NAMES
    ]

    if invalid_stats:
        raise ValueError(
            f"Unknown stats: {invalid_stats}"
        )

    if request.source != "player":
        raise ValueError(
            "Currently source must be 'player'."
        )

    if request.target not in PLAYER_TARGETS:
        raise ValueError(
            f"Unknown comparison target: {request.target}"
        )

    if (
        request.start_seconds is not None
        and request.end_seconds is not None
        and request.start_seconds > request.end_seconds
    ):
        raise ValueError(
            "start_seconds must be <= end_seconds."
        )


def average_snapshot(
    players,
    timestamp,
):
    if not players:
        raise ValueError(
            "Cannot average an empty player collection."
        )

    class AverageSnapshot:
        pass

    result = AverageSnapshot()

    for stat in STAT_NAMES:
        setattr(
            result,
            stat,
            sum(
                getattr(player, stat)
                for player in players
            ) / len(players),
        )

    result.timestamp = timestamp

    return result


def get_comparison_reference(
    player,
    snapshots,
    target,
):
    own_team_players = [
        p
        for p in snapshots
        if p.team == player.team
    ]

    enemy_team_players = [
        p
        for p in snapshots
        if p.team != player.team
    ]

    opponent_candidates = [
        p
        for p in enemy_team_players
        if p.lane == player.lane
    ]

    opponent = (
        opponent_candidates[0]
        if opponent_candidates
        else None
    )

    if target == "opponent":
        return opponent

    if target == "own_team":
        return TeamSnapshot(
            team=player.team,
            timestamp=player.timestamp,
            players=own_team_players,
        )

    if target == "enemy_team":
        enemy_team = 200 if player.team == 100 else 100

        return TeamSnapshot(
            team=enemy_team,
            timestamp=player.timestamp,
            players=enemy_team_players,
        )

    if target == "game":
        return GameSnapshot(
            timestamp=player.timestamp,
            players=snapshots,
        )

    if target == "own_team_average":
        return average_snapshot(
            own_team_players,
            player.timestamp,
        )

    if target == "own_team_excluding_self_average":
        return average_snapshot(
            [
                p
                for p in own_team_players
                if p.participant_id != player.participant_id
            ],
            player.timestamp,
        )

    if target == "enemy_team_average":
        return average_snapshot(
            enemy_team_players,
            player.timestamp,
        )

    if target == "enemy_team_excluding_opponent_average":
        return average_snapshot(
            [
                p
                for p in enemy_team_players
                if opponent is None
                or p.participant_id != opponent.participant_id
            ],
            player.timestamp,
        )

    if target == "game_average":
        return average_snapshot(
            snapshots,
            player.timestamp,
        )

    raise ValueError(
        f"Unsupported target: {target}"
    )


def compare_player(
    snapshots,
    request: ComparisonRequest,
):
    validate_comparison_request(request)

    players_by_id = {
        player.participant_id: player
        for player in snapshots
    }

    if request.source_id is None:
        raise ValueError(
            "source_id is required."
        )

    player = players_by_id.get(
        request.source_id
    )

    if player is None:
        raise ValueError(
            f"Player {request.source_id} not found."
        )

    reference = get_comparison_reference(
        player,
        snapshots,
        request.target,
    )

    if reference is None:
        raise ValueError(
            "Could not determine comparison reference."
        )

    result = {
        "player": player,
        "target": request.target,
        "timestamp": player.timestamp,
        "stats": {},
    }

    for stat in request.stats:
        result["stats"][stat] = calculate_metric(
            getattr(player, stat),
            getattr(reference, stat),
        )

    return result


def get_stats(obj):
    return {
        # Add 0.0 as the fallback if the attribute doesn't exist on the object
        stat: getattr(obj, stat, 0.0)
        for stat in STAT_NAMES
    }


def get_total_stats(obj):
    return get_stats(obj)


def get_average_stats(players):
    return average_players(players)


def calculate_metric(
    value: float,
    reference: float,
) -> dict:

    difference = value - reference

    ratio = (
        value / reference
        if reference != 0
        else None
    )

    share_of_combined = (
        value / (value + reference)
        if value + reference != 0
        else None
    )

    share_of_reference = (
        value / reference
        if reference != 0
        else None
    )

    relative_difference = (
        difference / reference
        if reference != 0
        else None
    )

    return {
        "value": value,
        "reference": reference,
        "difference": difference,
        "ratio": ratio,
        "share_of_combined": share_of_combined,
        "share_of_reference": share_of_reference,
        "relative_difference": relative_difference,
    }


def compare_stats(
    stats: dict,
    reference_stats: dict,
) -> dict:

    return {
        stat: calculate_metric(
            stats[stat],
            reference_stats[stat],
        )
        for stat in STAT_NAMES
    }


def calculate_player_comparisons(
    player: PlayerSnapshot,
    opponent: PlayerSnapshot,
    own_team: TeamSnapshot,
    enemy_team: TeamSnapshot,
    game: GameSnapshot,
) -> dict:

    player_stats = get_stats(player)
    opponent_stats = get_stats(opponent)

    own_team_total = get_stats(own_team)
    enemy_team_total = get_stats(enemy_team)
    game_total = get_stats(game)

    own_team_average = get_average_stats(
        own_team.players
    )

    enemy_team_average = get_average_stats(
        enemy_team.players
    )

    game_average = get_average_stats(
        game.players
    )

    own_team_other_players = get_other_team_players(
        own_team.players,
        player,
    )

    own_team_other_average = get_average_stats(
        own_team_other_players
    )

    enemy_team_other_players = [
        enemy
        for enemy in enemy_team.players
        if enemy.participant_id != opponent.participant_id
    ]

    enemy_team_other_average = get_average_stats(
        enemy_team_other_players
    )

    result = {}

    for stat in STAT_NAMES:
        result[stat] = {
            "vs_opponent": calculate_metric(
                player_stats[stat],
                opponent_stats[stat],
            ),

            "vs_own_team": {
                "total": calculate_metric(
                    player_stats[stat],
                    own_team_total[stat],
                ),
                "average": calculate_metric(
                    player_stats[stat],
                    own_team_average[stat],
                ),
            },

            "vs_own_team_excluding_self_average": calculate_metric(
                player_stats[stat],
                own_team_other_average[stat],
            ),

            "vs_enemy_team": {
                "total": calculate_metric(
                    player_stats[stat],
                    enemy_team_total[stat],
                ),
                "average": calculate_metric(
                    player_stats[stat],
                    enemy_team_average[stat],
                ),
            },

            "vs_enemy_team_excluding_opponent_average": calculate_metric(
                player_stats[stat],
                enemy_team_other_average[stat],
            ),

            "vs_game": {
                "total": calculate_metric(
                    player_stats[stat],
                    game_total[stat],
                ),
                "average": calculate_metric(
                    player_stats[stat],
                    game_average[stat],
                ),
            },
        }

    return result


def calculate_lane_comparisons(
    lane: LaneSnapshot,
    opponent_lane: LaneSnapshot,
    own_team: TeamSnapshot,
    enemy_team: TeamSnapshot,
    game: GameSnapshot,
) -> dict:

    lane_total = get_stats(lane)
    opponent_lane_total = get_stats(opponent_lane)

    lane_average = get_average_stats(
        lane.players
    )

    opponent_lane_average = get_average_stats(
        opponent_lane.players
    )

    own_team_total = get_stats(own_team)
    enemy_team_total = get_stats(enemy_team)
    game_total = get_stats(game)

    own_team_average = get_average_stats(
        own_team.players
    )

    enemy_team_average = get_average_stats(
        enemy_team.players
    )

    game_average = get_average_stats(
        game.players
    )

    own_team_other_players = [
        player
        for player in own_team.players
        if player not in lane.players
    ]

    enemy_team_other_players = [
        player
        for player in enemy_team.players
        if player not in opponent_lane.players
    ]

    own_team_other_average = get_average_stats(
        own_team_other_players
    )

    enemy_team_other_average = get_average_stats(
        enemy_team_other_players
    )

    result = {}

    for stat in STAT_NAMES:
        result[stat] = {
            "vs_opponent_lane": {
                "total": calculate_metric(
                    lane_total[stat],
                    opponent_lane_total[stat],
                ),
                "average": calculate_metric(
                    lane_average[stat],
                    opponent_lane_average[stat],
                ),
            },

            "vs_own_team": {
                "total": calculate_metric(
                    lane_total[stat],
                    own_team_total[stat],
                ),
                "average": calculate_metric(
                    lane_average[stat],
                    own_team_average[stat],
                ),
            },

            "vs_own_team_excluding_lane_average": calculate_metric(
                lane_average[stat],
                own_team_other_average[stat],
            ),

            "vs_enemy_team": {
                "total": calculate_metric(
                    lane_total[stat],
                    enemy_team_total[stat],
                ),
                "average": calculate_metric(
                    lane_average[stat],
                    enemy_team_average[stat],
                ),
            },

            "vs_enemy_team_excluding_opponent_lane_average": calculate_metric(
                lane_average[stat],
                enemy_team_other_average[stat],
            ),

            "vs_game": {
                "total": calculate_metric(
                    lane_total[stat],
                    game_total[stat],
                ),
                "average": calculate_metric(
                    lane_average[stat],
                    game_average[stat],
                ),
            },
        }

    return result


def calculate_objective_comparisons(
    own_objectives: TeamObjectiveSnapshot,
    enemy_objectives: TeamObjectiveSnapshot,
) -> dict:
    """Compare objectives between two teams."""
    own_stats = aggregate_objectives(own_objectives)
    enemy_stats = aggregate_objectives(enemy_objectives)

    result = {}

    for objective in OBJECTIVE_NAMES:
        result[objective] = calculate_metric(
            own_stats[objective],
            enemy_stats[objective],
        )

    return result


def calculate_team_comparisons(
    own_team: TeamSnapshot,
    enemy_team: TeamSnapshot,
    game: GameSnapshot,
) -> dict:

    own_team_total = get_stats(own_team)
    enemy_team_total = get_stats(enemy_team)
    game_total = get_stats(game)

    own_team_average = get_average_stats(
        own_team.players
    )

    enemy_team_average = get_average_stats(
        enemy_team.players
    )

    game_average = get_average_stats(
        game.players
    )

    result = {}

    for stat in STAT_NAMES:
        result[stat] = {
            "vs_opponent_team": calculate_metric(
                own_team_total[stat],
                enemy_team_total[stat],
            ),

            "vs_game": {
                "total": calculate_metric(
                    own_team_total[stat],
                    game_total[stat],
                ),
                "average": calculate_metric(
                    own_team_average[stat],
                    game_average[stat],
                ),
            },
        }

    return result


def build_player_analysis(
    snapshots: list[PlayerSnapshot],
    teams: dict[int, TeamSnapshot],
    game: GameSnapshot,
) -> list[PlayerAnalysis]:

    results = []

    for player in snapshots:

        opponents = [
            opponent
            for opponent in snapshots
            if opponent.team != player.team
            and opponent.lane == player.lane
        ]

        if not opponents:
            continue

        opponent = opponents[0]

        own_team = teams[player.team]

        enemy_team = next(
            team
            for team_id, team in teams.items()
            if team_id != player.team
        )

        comparisons = calculate_player_comparisons(
            player,
            opponent,
            own_team,
            enemy_team,
            game,
        )

        results.append(
            PlayerAnalysis(
                player=player,
                opponent=opponent,
                comparisons=comparisons,
            )
        )

    return results


def build_lane_analysis(
    snapshots: list[PlayerSnapshot],
    teams: dict[int, TeamSnapshot],
    game: GameSnapshot,
) -> dict[str, LaneAnalysis]:

    lanes = [
        "TOP",
        "JUNGLE",
        "MIDDLE",
        "BOTTOM",
        "UTILITY",
    ]

    results = {}

    for lane in lanes:

        own_lane_players = [
            player
            for player in snapshots
            if player.team == 100
            and player.lane == lane
        ]

        opponent_lane_players = [
            player
            for player in snapshots
            if player.team == 200
            and player.lane == lane
        ]

        if not own_lane_players or not opponent_lane_players:
            continue

        own_lane = LaneSnapshot(
            team=100,
            lane=lane,
            timestamp=game.timestamp,
            players=own_lane_players,
        )

        opponent_lane = LaneSnapshot(
            team=200,
            lane=lane,
            timestamp=game.timestamp,
            players=opponent_lane_players,
        )

        comparisons = calculate_lane_comparisons(
            own_lane,
            opponent_lane,
            teams[100],
            teams[200],
            game,
        )

        results[lane] = LaneAnalysis(
            lane=lane,
            own_lane=own_lane,
            opponent_lane=opponent_lane,
            comparisons=comparisons,
        )

    return results


def build_team_analysis(
    teams: dict[int, TeamSnapshot],
    game: GameSnapshot,
) -> TeamAnalysis:

    own_team = teams[100]
    enemy_team = teams[200]

    comparisons = calculate_team_comparisons(
        own_team,
        enemy_team,
        game,
    )

    objective_comparisons = calculate_objective_comparisons(
        own_team.objectives,
        enemy_team.objectives,
    )

    return TeamAnalysis(
        team=100,
        own_team=own_team,
        opponent_team=enemy_team,
        comparisons=comparisons,
        objective_comparisons=objective_comparisons,
    )


def build_match_analysis(
    snapshots: list[PlayerSnapshot],
    objectives: dict[int, TeamObjectiveSnapshot] = None,
) -> MatchAnalysis:

    if objectives is None:
        objectives = {
            100: TeamObjectiveSnapshot(),
            200: TeamObjectiveSnapshot(),
        }

    timestamp = snapshots[0].timestamp

    game = GameSnapshot(
        timestamp=timestamp,
        players=snapshots,
        objectives=objectives,
    )

    teams = {
        100: TeamSnapshot(
            team=100,
            timestamp=timestamp,
            players=[
                player
                for player in snapshots
                if player.team == 100
            ],
            objectives=objectives.get(100, TeamObjectiveSnapshot()),
        ),

        200: TeamSnapshot(
            team=200,
            timestamp=timestamp,
            players=[
                player
                for player in snapshots
                if player.team == 200
            ],
            objectives=objectives.get(200, TeamObjectiveSnapshot()),
        ),
    }

    player_analysis = build_player_analysis(
        snapshots,
        teams,
        game,
    )

    lane_analysis = build_lane_analysis(
        snapshots,
        teams,
        game,
    )

    team_analysis = build_team_analysis(
        teams,
        game,
    )

    return MatchAnalysis(
        game=game,
        teams=teams,
        players=player_analysis,
        lanes=lane_analysis,
        team_comparisons=team_analysis,
    )


def get_other_team_players(
    players,
    player,
):
    return [
        other
        for other in players
        if other.team == player.team
        and other.participant_id != player.participant_id
    ]


def create_snapshot_from_players(
    players,
    team,
    timestamp,
):
    return TeamSnapshot(
        team=team,
        timestamp=timestamp,
        players=players,
    )