from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlayerSnapshot:
    participant_id: int
    timestamp: int

    name: str
    tag: str
    champion: str

    team: int
    lane: str
    role: str

    level: int
    xp: int
    gold: int
    cs: int

    # Combat & Rate stats
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    kda: float = 0.0
    gold_per_minute: float = 0.0
    cs_per_minute: float = 0.0

    attack_damage: float = 0.0
    ability_power: float = 0.0
    health: float = 0.0
    max_health: float = 0.0
    armor: float = 0.0
    magic_resist: float = 0.0
    attack_speed: float = 0.0
    movement_speed: float = 0.0

    ability_haste: float = 0.0
    armor_pen: float = 0.0
    armor_pen_percent: float = 0.0
    magic_pen: float = 0.0
    magic_pen_percent: float = 0.0
    health_regen: float = 0.0
    lifesteal: float = 0.0
    omnivamp: float = 0.0

    # Advanced & Vision Metrics
    total_damage: float = 0.0
    kp_pct: float = 0.0
    gold_share: float = 0.0
    dmg_share: float = 0.0
    gold_efficiency: float = 0.0
    vision_score: float = 0.0
    wards_placed: int = 0
    wards_killed: int = 0


def aggregate_players(players: list[PlayerSnapshot]) -> dict:
    if not players:
        return {}

    return {
        "gold": sum(p.gold for p in players),
        "xp": sum(p.xp for p in players),
        "cs": sum(p.cs for p in players),
        "level": sum(p.level for p in players),
        "kills": sum(p.kills for p in players),
        "deaths": sum(p.deaths for p in players),
        "assists": sum(p.assists for p in players),
        "kda": sum(p.kda for p in players) / len(players),
        "gold_per_minute": sum(p.gold_per_minute for p in players),
        "cs_per_minute": sum(p.cs_per_minute for p in players),
        "attack_damage": sum(p.attack_damage for p in players),
        "ability_power": sum(p.ability_power for p in players),
        "health": sum(p.health for p in players),
        "max_health": sum(p.max_health for p in players),
        "armor": sum(p.armor for p in players),
        "magic_resist": sum(p.magic_resist for p in players),
        "attack_speed": sum(p.attack_speed for p in players),
        "movement_speed": sum(p.movement_speed for p in players),
        "ability_haste": sum(p.ability_haste for p in players),
        "armor_pen": sum(p.armor_pen for p in players),
        "armor_pen_percent": sum(p.armor_pen_percent for p in players),
        "magic_pen": sum(p.magic_pen for p in players),
        "magic_pen_percent": sum(p.magic_pen_percent for p in players),
        "health_regen": sum(p.health_regen for p in players),
        "lifesteal": sum(p.lifesteal for p in players),
        "omnivamp": sum(p.omnivamp for p in players),
        "total_damage": sum(p.total_damage for p in players),
        "kp_pct": sum(p.kp_pct for p in players) / len(players),
        "gold_share": sum(p.gold_share for p in players),
        "dmg_share": sum(p.dmg_share for p in players),
        "gold_efficiency": sum(p.gold_efficiency for p in players) / len(players),
        "vision_score": sum(p.vision_score for p in players),
        "wards_placed": sum(p.wards_placed for p in players),
        "wards_killed": sum(p.wards_killed for p in players),
    }


def average_players(players: list[PlayerSnapshot]) -> dict:
    if not players:
        return {}

    count = len(players)
    totals = aggregate_players(players)

    avg_dict = {stat: value / count for stat, value in totals.items()}
    avg_dict["kda"] = totals["kda"]
    return avg_dict


class BaseGroupSnapshot:
    """Shared aggregation properties across snapshot groups."""
    players: list[PlayerSnapshot]

    @property
    def gold(self) -> int: return sum(p.gold for p in self.players)
    @property
    def xp(self) -> int: return sum(p.xp for p in self.players)
    @property
    def cs(self) -> int: return sum(p.cs for p in self.players)
    @property
    def level(self) -> int: return sum(p.level for p in self.players)
    @property
    def kills(self) -> int: return sum(p.kills for p in self.players)
    @property
    def deaths(self) -> int: return sum(p.deaths for p in self.players)
    @property
    def assists(self) -> int: return sum(p.assists for p in self.players)
    @property
    def kda(self) -> float:
        return sum(p.kda for p in self.players) / len(self.players) if self.players else 0.0
    @property
    def gold_per_minute(self) -> float: return sum(p.gold_per_minute for p in self.players)
    @property
    def cs_per_minute(self) -> float: return sum(p.cs_per_minute for p in self.players)
    @property
    def attack_damage(self) -> float: return sum(p.attack_damage for p in self.players)
    @property
    def ability_power(self) -> float: return sum(p.ability_power for p in self.players)
    @property
    def health(self) -> float: return sum(p.health for p in self.players)
    @property
    def max_health(self) -> float: return sum(p.max_health for p in self.players)
    @property
    def armor(self) -> float: return sum(p.armor for p in self.players)
    @property
    def magic_resist(self) -> float: return sum(p.magic_resist for p in self.players)
    @property
    def attack_speed(self) -> float: return sum(p.attack_speed for p in self.players)
    @property
    def movement_speed(self) -> float: return sum(p.movement_speed for p in self.players)
    @property
    def ability_haste(self) -> float: return sum(p.ability_haste for p in self.players)
    @property
    def armor_pen(self) -> float: return sum(p.armor_pen for p in self.players)
    @property
    def armor_pen_percent(self) -> float: return sum(p.armor_pen_percent for p in self.players)
    @property
    def magic_pen(self) -> float: return sum(p.magic_pen for p in self.players)
    @property
    def magic_pen_percent(self) -> float: return sum(p.magic_pen_percent for p in self.players)
    @property
    def health_regen(self) -> float: return sum(p.health_regen for p in self.players)
    @property
    def lifesteal(self) -> float: return sum(p.lifesteal for p in self.players)
    @property
    def omnivamp(self) -> float: return sum(p.omnivamp for p in self.players)

    @property
    def total_damage(self) -> float: return sum(p.total_damage for p in self.players)
    @property
    def kp_pct(self) -> float:
        return sum(p.kp_pct for p in self.players) / len(self.players) if self.players else 0.0
    @property
    def gold_share(self) -> float: return sum(p.gold_share for p in self.players)
    @property
    def dmg_share(self) -> float: return sum(p.dmg_share for p in self.players)
    @property
    def gold_efficiency(self) -> float:
        return sum(p.gold_efficiency for p in self.players) / len(self.players) if self.players else 0.0
    @property
    def vision_score(self) -> float: return sum(p.vision_score for p in self.players)
    @property
    def wards_placed(self) -> int: return sum(p.wards_placed for p in self.players)
    @property
    def wards_killed(self) -> int: return sum(p.wards_killed for p in self.players)


@dataclass
class TeamObjectiveSnapshot:
    turrets: int = 0
    outer_turrets: int = 0
    inner_turrets: int = 0
    inhibitor_turrets: int = 0
    nexus_turrets: int = 0
    inhibitors: int = 0
    dragons: int = 0
    elemental_drakes: int = 0
    dragon_soul: Optional[str] = None
    heralds: int = 0
    barons: int = 0
    grubs: int = 0

@dataclass
class TeamSnapshot(BaseGroupSnapshot):
    team: int
    timestamp: int
    players: list[PlayerSnapshot]
    objectives: TeamObjectiveSnapshot = field(default_factory=TeamObjectiveSnapshot)


@dataclass
class LaneSnapshot(BaseGroupSnapshot):
    team: int
    lane: str
    timestamp: int
    players: list[PlayerSnapshot]


@dataclass
class GameSnapshot(BaseGroupSnapshot):
    timestamp: int
    players: list[PlayerSnapshot]
    objectives: dict[int, TeamObjectiveSnapshot] = field(default_factory=lambda: {100: TeamObjectiveSnapshot(), 200: TeamObjectiveSnapshot()})


def aggregate_objectives(objectives: TeamObjectiveSnapshot) -> dict:
    return {
        "turrets": objectives.turrets,
        "outer_turrets": objectives.outer_turrets,
        "inner_turrets": objectives.inner_turrets,
        "inhibitor_turrets": objectives.inhibitor_turrets,
        "nexus_turrets": objectives.nexus_turrets,
        "inhibitors": objectives.inhibitors,
        "dragons": objectives.dragons,
        "elemental_drakes": objectives.elemental_drakes,
        "heralds": objectives.heralds,
        "barons": objectives.barons,
        "grubs": objectives.grubs,
    }


@dataclass
class PlayerAnalysis:
    player: PlayerSnapshot
    opponent: PlayerSnapshot
    comparisons: dict


@dataclass
class LaneAnalysis:
    lane: str
    own_lane: LaneSnapshot
    opponent_lane: LaneSnapshot
    comparisons: dict


@dataclass
class TeamAnalysis:
    team: int
    own_team: TeamSnapshot
    opponent_team: TeamSnapshot
    comparisons: dict
    objective_comparisons: dict


@dataclass
class MatchAnalysis:
    game: GameSnapshot
    teams: dict[int, TeamSnapshot]
    players: list[PlayerAnalysis]
    lanes: dict[str, LaneAnalysis]
    team_comparisons: TeamAnalysis


@dataclass
class TimelineAnalysis:
    interval_seconds: int
    analyses: list[MatchAnalysis]