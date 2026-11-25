#!/usr/bin/env python3
"""
NHL confirmed-goalie alerts.
Scrapes Daily Faceoff's starting goalies page and sends a push notification
via ntfy.sh whenever a goalie becomes "Confirmed".
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


def fetch_confirmed_goalies(day: str):
    url = f"https://www.dailyfaceoff.com/starting-goalies/{day}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if resp.status_code != 200:
        return {}
    
    soup = BeautifulSoup(resp.text, "html.parser")
    confirmed_goalies = {}

    # Target specific player or goalie card items on the page
    cards = soup.find_all(["div", "article", "li"], class_=lambda c: c and any(term in c.lower() for term in ["goalie", "player", "matchup"]))
    if not cards:
        cards = soup.find_all("div")

    for card in cards:
        text = card.get_text(" ", strip=True)
        # Look only for blocks that explicitly indicate confirmed starting status
        if "confirmed" in text.lower():
            lines = [line.strip() for line in card.get_text("\n", strip=True).split("\n") if line.strip()]
            
            goalie_name = None
            for idx, line in enumerate(lines):
                if "confirmed" in line.lower() and idx > 0:
                    potential_name = lines[idx - 1]
                    # Filter to ensure it looks like a valid player name (2-3 words, no matchup text)
                    if len(potential_name.split()) in [2, 3] and "vs" not in potential_name.lower():
                        goalie_name = potential_name
                        break
            
            if goalie_name:
                confirmed_goalies[goalie_name] = f"{goalie_name} has been officially confirmed as the starting goalie."
                
    return confirmed_goalies


def notify(goalie, detail):
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=detail.encode(),
        headers={"Title": f"{goalie} confirmed in net", "Tags": "goal_net,ice_hockey"},
        timeout=15,
    )


def check_once():
    # Load previously sent state
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    today = datetime.now(EASTERN).strftime("%Y-%m-%d")
    
    # Keep only today's records in state memory
    state = {k: v for k, v in state.items() if k.startswith(today)}

    goalies = fetch_confirmed_goalies(today)
    if not goalies:
        print("No confirmed goalies found yet.")
        
    for goalie, detail in goalies.items():
        skey = f"{today}:{goalie}"
        # Only notify if we haven't already sent an alert for this specific goalie today
        if state.get(skey) != "sent":
            notify(goalie, detail)
            print(f"Sent alert: {goalie}")
            state[skey] = "sent"
            
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
