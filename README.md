# League Advantage Calculator

A Python tool for analyzing League of Legends match timelines and making configurable player/stat comparisons.

## Project structure

```text
LeagueAdvantageCalculator/
├── main.py
├── advantages.py
├── comparisons.py
├── models.py
├── riot_api.py
└── .venv/
```

### `main.py`
Entry point. Retrieves the match/timeline, builds snapshots and analyses, creates `ComparisonRequest`s, and prints results.

### `models.py`
Contains the data models, including `PlayerSnapshot` and the match-analysis models.

### `advantages.py`
Contains the match/player advantage-analysis logic exposed through `build_match_analysis()`.

### `comparisons.py`
Contains the customizable comparison layer:
```python
ComparisonRequest(...)
compare_timeline(analyses, request)
```

### `riot_api.py`
Contains Riot API access functions such as:
```python
get_account_by_riot_id()
get_match_ids()
get_match()
get_timeline()
```

---

# Setup

## Virtual environment

Windows:

```powershell
D:\info\python\LeagueAdvantageCalculator\.venv\Scripts\activate
```

Or run directly:

```powershell
D:\info\python\LeagueAdvantageCalculator\.venv\Scripts\python.exe main.py
```

If the project has a `requirements.txt`:

```powershell
pip install -r requirements.txt
```

## Riot API key

Configure the API key using the mechanism already implemented in `riot_api.py`.

Do **not** commit the API key to Git.

Typical environment-variable form:

```text
RIOT_API_KEY=RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Use the exact variable name expected by your `riot_api.py`.

---

# Running

From the project directory:

```powershell
python main.py
```

The program currently:

1. Looks up the configured Riot ID.
2. Gets recent match IDs.
3. Selects one match.
4. Gets the match and timeline.
5. Converts timeline frames into `PlayerSnapshot`s.
6. Builds match analyses.
7. Runs a custom comparison.
8. Prints the results.

---

# Changing the analyzed player

In `main.py`:

```python
account = get_account_by_riot_id(
    "døinB ryze hack",
    "EUNE"
)
```

Change the Riot ID and region as required:

```python
account = get_account_by_riot_id(
    "PlayerName",
    "EUNE"
)
```

---

# Changing the match

Currently:

```python
match_ids = get_match_ids(puuid, count=20)
match_id = match_ids[0]
```

This requests 20 recent matches and analyzes the first returned match.

For experimentation:

```python
match_id = match_ids[1]
```

or:

```python
match_id = match_ids[5]
```

A future improvement would be selecting a match by ID, date, queue, champion, etc.

---

# Timeline sampling

Current sampling:

```python
analyses = analyze_timeline(
    frames,
    players,
    interval_seconds=60,
)
```

Every 60 seconds is one analysis point.

Use 30-second sampling:

```python
interval_seconds=30
```

or two-minute sampling:

```python
interval_seconds=120
```

The Riot timeline may not contain a frame at exactly the requested timestamp, so the project uses `get_closest_frame()`.

---

# Custom comparison system

The important interface is:

```python
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
```

Think of a request as:

```text
WHO → source_id
WHO/WHAT → target
WHAT → stats
WHEN → start/end
```

This keeps comparison selection separate from Riot API retrieval and presentation.

---

# 1. Selecting the source player

The source uses the match participant ID.

Current match example:

```text
1  Yasuo
2  Briar
3  Xerath
4  Malzahar
5  Blitzcrank
6  Zyra
7  Trundle
8  Ahri
9  Kaisa
10 Nami
```

Therefore:

```python
source_id=4
```

means Malzahar.

For Yasuo:

```python
source_id=1
```

For Xerath:

```python
source_id=3
```

Use the participant IDs printed by `main.py`.

---

# 2. Selecting the target

The target controls who/what the source is compared against.

For a direct opponent:

```python
target="opponent"
```

The exact target names supported by `comparisons.py` are the source of truth. Do not invent a new target string unless you also implement it there.

The broader analysis distinguishes concepts such as:

- direct opponent
- own team
- own team excluding self
- enemy team
- enemy team excluding direct opponent
- entire game

These answer different questions and should remain separate.

---

# 3. Selecting stats

Example:

```python
stats=[
    "gold",
    "xp",
    "cs",
    "ability_power",
    "attack_damage",
]
```

You can request only a subset:

```python
stats=[
    "gold",
    "cs",
]
```

The current `PlayerSnapshot` contains:

```text
level
xp
gold
cs

attack_damage
ability_power
health
max_health
armor
magic_resist
attack_speed
movement_speed

ability_haste
armor_pen
armor_pen_percent
magic_pen
magic_pen_percent
health_regen
lifesteal
omnivamp
```

However, a field existing on `PlayerSnapshot` does **not** automatically mean it is supported by `comparisons.py`. The comparison layer must also know how to resolve it.

---

# 4. Selecting the time range

Example:

```python
start="5:00",
end="15:00",
```

Only results within that requested window are returned by `compare_timeline()`.

Examples:

```python
start="1:00",
end="30:00",
```

```python
start="10:00",
end="12:00",
```

The exact number of returned points depends on the timeline sampling interval.

---

# Example: lane advantage

```python
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
```

This answers:

> At each sampled point, how far ahead or behind is Malzahar compared with his direct opponent?

---

# Example: economy only

```python
request = ComparisonRequest(
    source_id=4,
    target="opponent",
    stats=[
        "gold",
        "cs",
    ],
    start="5:00",
    end="20:00",
)
```

---

# Example: combat stats

```python
request = ComparisonRequest(
    source_id=4,
    target="opponent",
    stats=[
        "ability_power",
        "attack_damage",
        "health",
        "armor",
        "magic_resist",
    ],
    start="10:00",
    end="25:00",
)
```

---

# Understanding a metric

Comparison results expose metrics such as:

```python
metric["value"]
metric["reference"]
metric["difference"]
metric["ratio"]
```

Conceptually:

```text
value       = source player's value
reference   = target/reference value
difference  = value - reference
ratio       = value / reference
```

Example:

```text
Ability Power    120.0 vs 100.0   Δ +20.0   1.20x
```

means:

- source = 120 AP
- reference = 100 AP
- difference = +20 AP
- ratio = 1.20×

If the ratio cannot be calculated, it may be `None`; the current formatter displays that as `—`.

---

# Team comparisons

The project intentionally keeps several comparison perspectives.

## Direct opponent

```text
Player vs direct opponent
```

Answers:

> How does this player compare with the specific opposing player?

## Own team — total

```text
Player vs total stat of all five allies
```

Useful for:

> How much does this player contribute relative to the team's total stat pool?

## Own team — average

```text
Player vs average stat of the five allies
```

Answers:

> Is this player above or below the team's overall average?

## Other own players — average

```text
Player vs average of the other four allies
```

This removes the player's own value from the reference and answers:

> How does this player compare with their actual teammates?

## Enemy team — total

```text
Player vs total stat of all five enemies
```

Useful for team-composition context.

## Enemy team — average

```text
Player vs average stat of all five enemies
```

Answers:

> Is this player above or below the average enemy?

## Other enemy players — average

```text
Player vs average of the other four enemies
```

This removes the direct opponent from the enemy reference.

## Entire game — total

```text
Player vs total stat across all ten players
```

## Entire game — average

```text
Player vs average stat across all ten players
```

### Why keep both total and average?

They answer different questions.

Average:

```text
"How strong is this player compared with a typical player?"
```

Total:

```text
"How large is this player's stat relative to the entire team's/game's stat pool?"
```

Both can be useful.

---

# Creating multiple comparison requests

You can define several requests:

```python
requests = [
    ComparisonRequest(
        source_id=4,
        target="opponent",
        stats=["gold", "xp", "cs"],
        start="5:00",
        end="20:00",
    ),

    ComparisonRequest(
        source_id=4,
        target="own_team",
        stats=["ability_power"],
        start="5:00",
        end="20:00",
    ),
]

for request in requests:
    results = compare_timeline(
        analyses,
        request,
    )

    # Format results here.
```

This is the recommended direction for making the tool reusable.

---

# Comparing multiple players

The same system can be used for every participant:

```python
for participant_id in players:
    request = ComparisonRequest(
        source_id=participant_id,
        target="opponent",
        stats=[
            "gold",
            "xp",
            "cs",
        ],
        start="5:00",
        end="20:00",
    )

    results = compare_timeline(
        analyses,
        request,
    )
```

This can eventually generate a full match report.

---

# Snapshot vs comparison logic

The architecture has several layers:

```text
Riot API
   ↓
timeline frame
   ↓
create_snapshot()
   ↓
PlayerSnapshot
   ↓
build_match_analysis()
   ↓
MatchAnalysis
   ↓
compare_timeline()
   ↑
ComparisonRequest
   ↓
ComparisonResult(s)
   ↓
output
```

If you add a new raw stat, make sure the whole chain supports it:

```text
Riot field
   ↓
create_snapshot()
   ↓
PlayerSnapshot field
   ↓
comparison stat resolver
   ↓
ComparisonRequest(stats=[...])
```

Adding a field to `PlayerSnapshot` alone is not enough.

---

# Troubleshooting

## `KeyError: 'value'`

This means the object being formatted does not have the metric structure the formatter expects.

Inspect the actual data:

```python
print(vars(first_analysis))
```

For dictionaries:

```python
print(some_dict)
```

Do not assume every nested object in `advantages.py` has:

```python
{
    "value": ...,
    "reference": ...,
    "difference": ...,
    "ratio": ...
}
```

The comparison layer should ideally normalize metrics into one consistent structure.

---

## `AttributeError` on analysis fields

If you see something like:

```text
AttributeError: 'MatchAnalysis' object has no attribute 'player_analyses'
```

the field name assumed by `main.py` does not exist in the current model.

Inspect it:

```python
first_analysis = analyses[0]
print(vars(first_analysis))
```

Use the field actually defined by `models.py`.

In the current `main.py` shown during development, player analyses are accessed through:

```python
analysis.players
```

provided that is still what `models.py` defines.

---

# Debugging nested objects

Useful temporary checks:

```python
first_analysis = analyses[0]

print(vars(first_analysis))
```

Then:

```python
print(vars(first_analysis.players[0]))
```

And:

```python
print(first_analysis.players[0].comparisons)
```

This is safer than guessing the structure from an earlier version of the code.

---

# Security

Do not commit:

- Riot API keys
- `.env` files containing secrets
- credentials
- private account information

Example `.gitignore`:

```gitignore
.env
*.env
__pycache__/
.venv/
```

---

# Recommended next improvements

## 1. Explicit target types

Make `comparisons.py` support clearly named targets such as:

```text
opponent
own_team
own_team_average
own_team_excluding_self_average
enemy_team
enemy_team_average
enemy_team_excluding_opponent_average
game
game_average
```

The exact names should be standardized in one place.

## 2. Explicit player targets

Support:

```python
source_id=4
target_id=9
```

This allows any player to be compared with any other player, not just the lane opponent.

## 3. More flexible selectors

Eventually support source selectors such as:

```text
participant ID
player name
champion
lane
role
```

## 4. Time-window aggregation

Beyond point-by-point results, support:

```text
point-by-point
average over interval
maximum advantage
minimum advantage
final advantage
integrated/area advantage
```

## 5. Export formats

Useful output formats:

```text
console
JSON
CSV
HTML
```

## 6. Charts

Plot statistics over time:

```text
player gold vs reference gold
player XP vs reference XP
player CS vs reference CS
player AP vs reference AP
```

## 7. Better match selection

Instead of:

```python
match_id = match_ids[0]
```

eventually support:

```text
specific match ID
latest match
latest ranked match
latest game on champion
date range
queue
```

---

# Minimal customization cheat sheet

Most experiments only require changing this:

```python
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
```

### Change player

```python
source_id=1
```

### Change target

```python
target="opponent"
```

Use a target supported by `comparisons.py`.

### Change stats

```python
stats=[
    "gold",
    "cs",
]
```

### Change start

```python
start="10:00"
```

### Change end

```python
end="25:00"
```

### Change timeline resolution

Separately change:

```python
interval_seconds=60
```

to:

```python
interval_seconds=30
```

---

# Design principle

Keep these responsibilities separate:

```text
Data collection
      ↓
Snapshot/model creation
      ↓
Match analysis
      ↓
Comparison selection
      ↓
Formatting/output
```

The goal is that changing:

```python
source_id
target
stats
start
end
```

does **not** require rewriting the Riot API or timeline processing code.

That separation is the foundation for turning the current calculator into a reusable League analysis/reporting system.
