#!/usr/bin/env python3
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
    
    # Target Daily Faceoff's specific game matchup and goalie card containers
    cards = soup.find_all(["div", "section", "article"], class_=lambda c: c and any(term in c.lower() for term in ["matchup", "goalie", "game-card", "starting-goalie"]))
    
    if not cards:
        cards = soup.find_all("div")
        
    return cards


def extract_alerts(game_cards):
    """Parse specific goalie names and confirmed statuses from Daily Faceoff."""
    out = {}
    for i, card in enumerate(game_cards):
        text = card.get_text(" | ", strip=True)
        
        # Look for blocks containing confirmation markers
        if "confirmed" in text.lower():
            lines = [line.strip() for line in card.get_text("\n", strip=True).split("\n") if line.strip()]
            
            goalie_name = None
            for idx, line in enumerate(lines):
                if "confirmed" in line.lower():
                    # Look right above the confirmation badge for the player's name
                    if idx > 0:
                        potential_name = lines[idx - 1]
                        # Filter out header labels or team names to isolate the player name
                        if len(potential_name.split()) in [2, 3] and "vs" not in potential_name.lower():
                            goalie_name = potential_name
                            break
            
            if goalie_name:
                key = f"goalie_{i}_{goalie_name.replace(' ', '_')}"
                detail = f"{goalie_name} has been officially confirmed as the starting goalie."
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
