from dataclasses import dataclass
from statistics import mean
from typing import Optional

STAT_NAMES = [
    "gold",
    "xp",
    "cs",
    "level",

    "kills",
    "deaths",
    "assists",
    "kda",
    "gold_per_minute",
    "cs_per_minute",

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


# ---------------------------------------------------------------------------
# Aggregation rules
# ---------------------------------------------------------------------------
#
# These are deliberately centralized.
#
# SUM:
#   Useful for resources / team-wide totals.
#
# AVERAGE:
#   More meaningful for stats that describe the typical individual.
#
# We can change these later without changing the comparison API.
#

STAT_AGGREGATION = {
    "gold": "sum",
    "gold_per_minute": "average",
    "xp": "sum",
    "cs": "sum",
    "cs_per_minute": "average",

    "level": "average",

    "kills": "sum",
    "deaths": "sum",
    "assists": "sum",
    "kda": "average",

    "attack_damage": "sum",
    "ability_power": "sum",
    "health": "sum",
    "max_health": "sum",

    "armor": "average",
    "magic_resist": "average",
    "attack_speed": "average",
    "movement_speed": "average",

    "ability_haste": "average",
    "armor_pen": "average",
    "armor_pen_percent": "average",
    "magic_pen": "average",
    "magic_pen_percent": "average",
    "health_regen": "average",
    "lifesteal": "average",
    "omnivamp": "average",
}


@dataclass
class ComparisonRequest:
    source_id: int

    target: str

    stats: list[str]

    target_id: Optional[int] = None

    start: Optional[str] = None
    end: Optional[str] = None

    aggregation: str = "auto"


@dataclass
class ComparisonResult:
    timestamp: int
    source_id: int
    target: str
    target_id: Optional[int]
    stats: dict


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_time(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    parts = value.split(":")

    if len(parts) == 1:
        return float(parts[0])

    if len(parts) == 2:
        minutes = int(parts[0])
        seconds = int(parts[1])

        return minutes * 60 + seconds

    raise ValueError(
        f"Invalid time format: {value!r}. "
        "Use 'MM:SS' or seconds."
    )


# ---------------------------------------------------------------------------
# Stat helpers
# ---------------------------------------------------------------------------

def get_stat(player, stat):
    return getattr(player, stat)


def aggregate_players(
    players,
    stat,
    aggregation="auto",
):
    if not players:
        return None

    if aggregation == "auto":
        aggregation = STAT_AGGREGATION[stat]

    values = [
        get_stat(player, stat)
        for player in players
    ]

    if aggregation == "sum":
        return sum(values)

    if aggregation == "average":
        return mean(values)

    raise ValueError(
        f"Unknown aggregation: {aggregation}"
    )


# ---------------------------------------------------------------------------
# Comparison math
# ---------------------------------------------------------------------------

def calculate_metric(
    value,
    reference,
):
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
        "relative_difference": relative_difference,
    }


# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------

def select_target_players(
    source,
    snapshots,
    target,
    target_id=None,
):
    own_team = [
        player
        for player in snapshots
        if player.team == source.team
    ]

    enemy_team = [
        player
        for player in snapshots
        if player.team != source.team
    ]

    if target == "player":

        if target_id is None:
            raise ValueError(
                "target_id is required when target='player'."
            )

        matches = [
            player
            for player in snapshots
            if player.participant_id == target_id
        ]

        if not matches:
            raise ValueError(
                f"Player {target_id} not found."
            )

        return matches

    if target == "opponent":

        opponents = [
            player
            for player in enemy_team
            if player.lane == source.lane
        ]

        if not opponents:
            raise ValueError(
                f"No lane opponent found for "
                f"{source.champion}."
            )

        return [opponents[0]]

    if target == "own_team":
        return own_team

    if target == "own_team_excluding_self":
        return [
            player
            for player in own_team
            if player.participant_id != source.participant_id
        ]

    if target == "enemy_team":
        return enemy_team

    if target == "enemy_team_excluding_opponent":

        opponent = select_target_players(
            source,
            snapshots,
            "opponent",
        )[0]

        return [
            player
            for player in enemy_team
            if player.participant_id != opponent.participant_id
        ]

    if target == "own_lane":

        return [
            player
            for player in own_team
            if player.lane == source.lane
        ]

    if target == "enemy_lane":

        return [
            player
            for player in enemy_team
            if player.lane == source.lane
        ]

    if target == "game":
        return list(snapshots)

    raise ValueError(
        f"Unknown comparison target: {target!r}"
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

VALID_TARGETS = {
    "player",
    "opponent",
    "own_team",
    "own_team_excluding_self",
    "enemy_team",
    "enemy_team_excluding_opponent",
    "own_lane",
    "enemy_lane",
    "game",
}


def validate_request(request):
    if request.target not in VALID_TARGETS:
        raise ValueError(
            f"Unknown target {request.target!r}. "
            f"Valid targets: {sorted(VALID_TARGETS)}"
        )

    if request.target == "player":
        if request.target_id is None:
            raise ValueError(
                "target_id is required for target='player'."
            )

        if request.target_id == request.source_id:
            raise ValueError(
                "source_id and target_id cannot be the same."
            )

    invalid_stats = [
        stat
        for stat in request.stats
        if stat not in STAT_NAMES
    ]

    if invalid_stats:
        raise ValueError(
            f"Unknown stats: {invalid_stats}"
        )

    if not request.stats:
        raise ValueError(
            "At least one stat is required."
        )


# ---------------------------------------------------------------------------
# One snapshot comparison
# ---------------------------------------------------------------------------

def compare_snapshot(
    snapshots,
    request: ComparisonRequest,
):
    validate_request(request)

    source = next(
        (
            player
            for player in snapshots
            if player.participant_id == request.source_id
        ),
        None,
    )

    if source is None:
        raise ValueError(
            f"Source player {request.source_id} not found."
        )

    target_players = select_target_players(
        source,
        snapshots,
        request.target,
        request.target_id,
    )

    result = {}

    for stat in request.stats:

        reference = aggregate_players(
            target_players,
            stat,
            request.aggregation,
        )

        result[stat] = calculate_metric(
            get_stat(source, stat),
            reference,
        )

    return ComparisonResult(
        timestamp=source.timestamp,
        source_id=source.participant_id,
        target=request.target,
        target_id=request.target_id,
        stats=result,
    )


# ---------------------------------------------------------------------------
# Timeline comparison
# ---------------------------------------------------------------------------

def compare_timeline(
    analyses,
    request: ComparisonRequest,
):
    validate_request(request)

    start = parse_time(request.start)
    end = parse_time(request.end)

    results = []

    for analysis in analyses:

        timestamp = analysis.game.timestamp / 1000

        if start is not None and timestamp < start:
            continue

        if end is not None and timestamp > end:
            continue

        result = compare_snapshot(
            analysis.game.players,
            request,
        )

        results.append(result)

    return results