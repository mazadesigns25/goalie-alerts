#!/usr/init/env python3
"""
NHL confirmed-goalie alerts.
Scrapes Daily Faceoff's starting goalies page directly and sends a push notification
via ntfy.sh whenever a goalie becomes "Confirmed" (or a confirmed goalie changes).

Setup:
  pip install requests beautifulsoup4
"""
import json, os, sys, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "zach-goalies-CHANGE-ME")
POLL_SECONDS = 600
STATE_FILE = Path("sent_goalies.json")
EASTERN = ZoneInfo("America/New_York")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def fetch_games(day: str):
    url = f"https://www.dailyfaceoff.com/starting-goalies/{day}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if resp.status_code != 200:
        return []
    
    soup = BeautifulSoup(resp.text, "html.parser")
    games_data = []

    matchup_cards = soup.find_all(lambda tag: tag.name == "div" and any("matchup" in c.lower() for c in tag.get("class", [])))
    
    if not matchup_cards:
        matchup_cards = soup.find_all("section")

    for card in matchup_cards:
        text_content = card.get_text(" ", strip=True)
        if "vs" in text_content.lower() or "-" in text_content:
            games_data.append(card)

    return games_data


def extract_alerts(game_cards):
    """Parse goalies and statuses directly from Daily Faceoff HTML elements."""
    out = {}
    for i, card in enumerate(game_cards):
        text = card.get_text(" | ", strip=True)
        if "confirmed" not in text.lower():
            continue
            
        lines = [line.strip() for line in card.get_text("\n", strip=True).split("\n") if line.strip()]
        
        goalie_name = None
        is_confirmed = False

        for idx, line in enumerate(lines):
            if "confirmed" in line.lower():
                is_confirmed = True
                if idx > 0:
                    goalie_name = lines[idx - 1]
            
        if is_confirmed and goalie_name:
            key = f"game_{i}"
            detail = f"Daily Faceoff Starting Goalies Update"
            out[key] = (goalie_name, detail)
            
    return out


def notify(goalie, detail):
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=detail.encode(),
        headers={"Title": f"{goalie} confirmed in net", "Tags": "goal_net,ice_hockey"},
        timeout=15,
    )


def check_once():
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    today = datetime.now(EASTERN).strftime("%Y-%m-%d")
    state = {k: v for k, v in state.items() if k.startswith(today)}

    cards = fetch_games(today)
    if not cards:
        print("No game cards parsed from Daily Faceoff.")
        
    alerts = extract_alerts(cards)
    for key, (goalie, detail) in alerts.items():
        skey = f"{today}:{key}"
        if state.get(skey) != goalie:
            notify(goalie, detail)
            print(f"Sent: {goalie} — {detail}")
            state[skey] = goalie
            
    STATE_FILE.write_text(json.dumps(state))


if __name__ == "__main__":
    if "--once" in sys.argv or "--debug" in sys.argv:
        check_once()
    else:
        while True:
            try:
                check_once()
            except Exception as e:
                print("Error:", e)
            time.sleep(POLL_SECONDS)
