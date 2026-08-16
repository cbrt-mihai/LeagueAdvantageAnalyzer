import os

import requests
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("RIOT_API_KEY")

print("API key loaded:", API_KEY is not None)
print("API key starts with:", API_KEY[:5] if API_KEY else None)

HEADERS = {
    "X-Riot-Token": API_KEY
}

BASE_URL = "https://europe.api.riotgames.com"


def get_account_by_riot_id(game_name: str, tag_line: str) -> dict:
    url = (
        f"{BASE_URL}/riot/account/v1/accounts/"
        f"by-riot-id/{game_name}/{tag_line}"
    )

    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()

    return response.json()


def get_match_ids(puuid: str, start: int = 0, count: int = 20) -> list[str]:
    url = (
        f"{BASE_URL}/lol/match/v5/matches/"
        f"by-puuid/{puuid}/ids"
    )

    params = {
        "start": start,
        "count": count,
    }

    response = requests.get(
        url,
        headers=HEADERS,
        params=params,
    )

    response.raise_for_status()

    return response.json()


def get_match(match_id: str, verbose = False) -> dict:
    url = f"{BASE_URL}/lol/match/v5/matches/{match_id}"

    response = requests.get(url, headers=HEADERS)

    if verbose:
        print("Status:", response.status_code)
        print("Response:", response.text)

    response.raise_for_status()

    return response.json()


def get_timeline(match_id: str, verbose = False) -> dict:
    url = f"{BASE_URL}/lol/match/v5/matches/{match_id}/timeline"

    response = requests.get(url, headers=HEADERS)

    if verbose:
        print("Status:", response.status_code)
        print("Response:", response.text)

    response.raise_for_status()

    return response.json()