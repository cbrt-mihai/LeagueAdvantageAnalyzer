from dataclasses import dataclass


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

    attack_damage: float
    ability_power: float
    health: float
    max_health: float
    armor: float
    magic_resist: float
    attack_speed: float
    movement_speed: float

    ability_haste: float
    armor_pen: float
    armor_pen_percent: float
    magic_pen: float
    magic_pen_percent: float
    health_regen: float
    lifesteal: float
    omnivamp: float


def aggregate_players(
    players: list[PlayerSnapshot],
) -> dict:
    if not players:
        return {}

    return {
        "gold": sum(player.gold for player in players),
        "xp": sum(player.xp for player in players),
        "cs": sum(player.cs for player in players),
        "level": sum(player.level for player in players),

        "attack_damage": sum(
            player.attack_damage for player in players
        ),

        "ability_power": sum(
            player.ability_power for player in players
        ),

        "health": sum(
            player.health for player in players
        ),

        "max_health": sum(
            player.max_health for player in players
        ),

        "armor": sum(
            player.armor for player in players
        ),

        "magic_resist": sum(
            player.magic_resist for player in players
        ),

        "attack_speed": sum(
            player.attack_speed for player in players
        ),

        "movement_speed": sum(
            player.movement_speed for player in players
        ),

        "ability_haste": sum(
            player.ability_haste for player in players
        ),

        "armor_pen": sum(
            player.armor_pen for player in players
        ),

        "armor_pen_percent": sum(
            player.armor_pen_percent for player in players
        ),

        "magic_pen": sum(
            player.magic_pen for player in players
        ),

        "magic_pen_percent": sum(
            player.magic_pen_percent for player in players
        ),

        "health_regen": sum(
            player.health_regen for player in players
        ),

        "lifesteal": sum(
            player.lifesteal for player in players
        ),

        "omnivamp": sum(
            player.omnivamp for player in players
        ),
    }


def average_players(
    players: list[PlayerSnapshot],
) -> dict:
    if not players:
        return {}

    count = len(players)

    totals = aggregate_players(players)

    return {
        stat: value / count
        for stat, value in totals.items()
    }


@dataclass
class TeamSnapshot:
    team: int
    timestamp: int
    players: list[PlayerSnapshot]

    @property
    def gold(self) -> int:
        return sum(player.gold for player in self.players)

    @property
    def xp(self) -> int:
        return sum(player.xp for player in self.players)

    @property
    def cs(self) -> int:
        return sum(player.cs for player in self.players)

    @property
    def level(self) -> int:
        return sum(player.level for player in self.players)

    @property
    def attack_damage(self) -> float:
        return sum(p.attack_damage for p in self.players)

    @property
    def ability_power(self) -> float:
        return sum(p.ability_power for p in self.players)

    @property
    def health(self) -> float:
        return sum(p.health for p in self.players)

    @property
    def max_health(self) -> float:
        return sum(p.max_health for p in self.players)

    @property
    def armor(self) -> float:
        return sum(p.armor for p in self.players)

    @property
    def magic_resist(self) -> float:
        return sum(p.magic_resist for p in self.players)

    @property
    def attack_speed(self) -> float:
        return sum(p.attack_speed for p in self.players)

    @property
    def movement_speed(self) -> float:
        return sum(p.movement_speed for p in self.players)

    @property
    def ability_haste(self) -> float:
        return sum(p.ability_haste for p in self.players)

    @property
    def armor_pen(self) -> float:
        return sum(p.armor_pen for p in self.players)

    @property
    def armor_pen_percent(self) -> float:
        return sum(p.armor_pen_percent for p in self.players)

    @property
    def magic_pen(self) -> float:
        return sum(p.magic_pen for p in self.players)

    @property
    def magic_pen_percent(self) -> float:
        return sum(p.magic_pen_percent for p in self.players)

    @property
    def health_regen(self) -> float:
        return sum(p.health_regen for p in self.players)

    @property
    def lifesteal(self) -> float:
        return sum(p.lifesteal for p in self.players)

    @property
    def omnivamp(self) -> float:
        return sum(p.omnivamp for p in self.players)


@dataclass
class LaneSnapshot:
    team: int
    lane: str
    timestamp: int
    players: list[PlayerSnapshot]

    @property
    def gold(self) -> int:
        return sum(player.gold for player in self.players)

    @property
    def xp(self) -> int:
        return sum(player.xp for player in self.players)

    @property
    def cs(self) -> int:
        return sum(player.cs for player in self.players)

    @property
    def level(self) -> int:
        return sum(player.level for player in self.players)

    @property
    def attack_damage(self) -> float:
        return sum(p.attack_damage for p in self.players)

    @property
    def ability_power(self) -> float:
        return sum(p.ability_power for p in self.players)

    @property
    def health(self) -> float:
        return sum(p.health for p in self.players)

    @property
    def max_health(self) -> float:
        return sum(p.max_health for p in self.players)

    @property
    def armor(self) -> float:
        return sum(p.armor for p in self.players)

    @property
    def magic_resist(self) -> float:
        return sum(p.magic_resist for p in self.players)

    @property
    def attack_speed(self) -> float:
        return sum(p.attack_speed for p in self.players)

    @property
    def movement_speed(self) -> float:
        return sum(p.movement_speed for p in self.players)

    @property
    def ability_haste(self) -> float:
        return sum(p.ability_haste for p in self.players)

    @property
    def armor_pen(self) -> float:
        return sum(p.armor_pen for p in self.players)

    @property
    def armor_pen_percent(self) -> float:
        return sum(p.armor_pen_percent for p in self.players)

    @property
    def magic_pen(self) -> float:
        return sum(p.magic_pen for p in self.players)

    @property
    def magic_pen_percent(self) -> float:
        return sum(p.magic_pen_percent for p in self.players)

    @property
    def health_regen(self) -> float:
        return sum(p.health_regen for p in self.players)

    @property
    def lifesteal(self) -> float:
        return sum(p.lifesteal for p in self.players)

    @property
    def omnivamp(self) -> float:
        return sum(p.omnivamp for p in self.players)


@dataclass
class GameSnapshot:
    timestamp: int
    players: list[PlayerSnapshot]

    @property
    def gold(self) -> int:
        return sum(player.gold for player in self.players)

    @property
    def xp(self) -> int:
        return sum(player.xp for player in self.players)

    @property
    def cs(self) -> int:
        return sum(player.cs for player in self.players)

    @property
    def level(self) -> int:
        return sum(player.level for player in self.players)

    @property
    def attack_damage(self) -> float:
        return sum(p.attack_damage for p in self.players)

    @property
    def ability_power(self) -> float:
        return sum(p.ability_power for p in self.players)

    @property
    def health(self) -> float:
        return sum(p.health for p in self.players)

    @property
    def max_health(self) -> float:
        return sum(p.max_health for p in self.players)

    @property
    def armor(self) -> float:
        return sum(p.armor for p in self.players)

    @property
    def magic_resist(self) -> float:
        return sum(p.magic_resist for p in self.players)

    @property
    def attack_speed(self) -> float:
        return sum(p.attack_speed for p in self.players)

    @property
    def movement_speed(self) -> float:
        return sum(p.movement_speed for p in self.players)

    @property
    def ability_haste(self) -> float:
        return sum(p.ability_haste for p in self.players)

    @property
    def armor_pen(self) -> float:
        return sum(p.armor_pen for p in self.players)

    @property
    def armor_pen_percent(self) -> float:
        return sum(p.armor_pen_percent for p in self.players)

    @property
    def magic_pen(self) -> float:
        return sum(p.magic_pen for p in self.players)

    @property
    def magic_pen_percent(self) -> float:
        return sum(p.magic_pen_percent for p in self.players)

    @property
    def health_regen(self) -> float:
        return sum(p.health_regen for p in self.players)

    @property
    def lifesteal(self) -> float:
        return sum(p.lifesteal for p in self.players)

    @property
    def omnivamp(self) -> float:
        return sum(p.omnivamp for p in self.players)


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
class MatchAnalysis:
    game: GameSnapshot
    teams: dict[int, TeamSnapshot]
    players: list[PlayerAnalysis]
    lanes: dict[str, LaneAnalysis]


@dataclass
class TimelineAnalysis:
    interval_seconds: int
    analyses: list[MatchAnalysis]