BLUE_TEAM_ID = 100
RED_TEAM_ID = 200

GOLD_SWING_THRESHOLD = 1500
XP_SWING_THRESHOLD = 2000
MIN_GOLD_SWING_THRESHOLD = 800
KILLS_THRESHOLD = 3

STAT_SCORE_WEIGHT = 0.7
OBJ_SCORE_WEIGHT = 0.3

ADVANTAGE_STRONG_THRESHOLD = 40
ADVANTAGE_MODERATE_THRESHOLD = 20
ADVANTAGE_SLIGHT_THRESHOLD = 10

ADVANTAGE_AHEAD = 5

SMALLEST_NONZERO = 0.00001

LANE_ORDER = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

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