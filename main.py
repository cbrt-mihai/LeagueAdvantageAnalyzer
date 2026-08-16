from riot_api import (
    get_account_by_riot_id,
    get_match_ids,
    get_match,
    get_timeline,
)

from comparisons import (
    ComparisonRequest,
    compare_timeline,
)

from models import PlayerSnapshot
from advantages import build_match_analysis


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
        snapshot = create_snapshot(
            frame,
            player_info
        )

        snapshots.append(snapshot)

    return snapshots


def analyze_timeline(
    frames,
    players,
    interval_seconds=60,
):
    analyses = []

    interval_ms = interval_seconds * 1000

    max_timestamp = frames[-1]["timestamp"]

    timestamp = interval_ms

    while timestamp <= max_timestamp:

        frame = get_closest_frame(
            frames,
            timestamp,
        )

        snapshots = create_snapshots(
            frame,
            players,
        )

        analysis = build_match_analysis(
            snapshots,
        )

        analyses.append(
            analysis
        )

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

    print("\n" + "=" * 72)
    print("PLAYERS")
    print("=" * 72)

    print(
        f"  {'ID':>2}  "
        f"{'Champion':<14} "
        f"{'Player':<22} "
        f"{'Team':<6} "
        f"{'Position':<10}"
    )

    print("  " + "-" * 66)

    for participant_id, player in players.items():
        print(
            f"  {participant_id:>2}  "
            f"{player['champion']:<14} "
            f"{player['name']:<22} "
            f"{player['team']:<6} "
            f"{player['lane']:<10}"
        )

    analyses = analyze_timeline(
        frames,
        players,
        interval_seconds=60,
    )

    print(
        f"\nGenerated {len(analyses)} analyses."
    )

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
        f"\n  Time:   {request.start} → {request.end}"
        f"\n  Stats:  {', '.join(request.stats)}"
    )

    for result in results:

        minute = result.timestamp / 1000 / 60

        print(
            f"\n  {minute:5.1f} min"
        )

        for stat, metric in result.stats.items():

            ratio = metric["ratio"]

            if ratio is None:
                ratio_text = "—"
            else:
                ratio_text = f"{ratio:.2f}x"

            print(
                f"    {stat:<20}"
                f"{metric['value']:>9.1f}"
                f" vs {metric['reference']:>9.1f}"
                f"   Δ {metric['difference']:>+9.1f}"
                f"   {ratio_text:>7}"
            )


if __name__ == "__main__":
    main()