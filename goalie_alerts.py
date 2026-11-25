#!/usr/bin/env python3
"""
NHL confirmed-goalie alerts.
Polls Daily Faceoff's starting goalies page and sends a push notification
via ntfy.sh whenever a goalie becomes "Confirmed" (or a confirmed goalie changes).

Setup:
  pip install requests
1. Install the ntfy app on your phone, subscribe to a hard-to-guess topic.
2. Set NTFY_TOPIC below (or as an env var).
3. python goalie_alerts.py            # loops every 10 min
     python goalie_alerts.py --once     # single check (for cron / Actions)
     python goalie_alerts.py --debug    # dumps the page JSON to debug.json
"""
import json, os, re, sys, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "zach-goalies-CHANGE-ME")
POLL_SECONDS = 600
STATE_FILE = Path("sent_goalies.json")
EASTERN = ZoneInfo("America/New_York")
HEADERS = {"User-Agent": "Mozilla/5.0 (personal goalie alert script)"}


def fetch_games(day: str):
    url = f"https://www.dailyfaceoff.com/starting-goalies/{day}"
    html = requests.get(url, headers=HEADERS, timeout=20).text
    
    # Try looking for __NEXT_DATA__ first
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S,
    )
    if not m:
        # Fallback to other embedded JSON data blocks if the tag ID changes
        m = re.search(r'\{"props":.*?\n\s*</script>', html, re.S)
        if not m:
            raise RuntimeError("Could not find game data on the page layout")
            
    raw_json = m.group(1).strip() if m.lastindex and m.group(1) else m.group(0)
    # Clean trailing script tag closing chars if matched by fallback
    raw_json = re.sub(r'</script>\s*$', '', raw_json)
    
    data = json.loads(raw_json)
    if "--debug" in sys.argv:
        Path("debug.json").write_text(json.dumps(data, indent=2))
    return list(find_games(data))


def find_games(node):
    """Walk the JSON and yield any dict that looks like a game with goalie fields."""
    if isinstance(node, dict):
        if any(k.endswith("GoalieName") for k in node):
            yield node
        for v in node.values():
            yield from find_games(v)
    elif isinstance(node, list):
        for v in node:
            yield from find_games(v)


def extract_alerts(games):
    """Return {key: (goalie, message)} for every confirmed goalie."""
    out = {}
    for g in games:
        when = g.get("date") or g.get("startTime") or g.get("gameTime") or ""
        try:
            t = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(EASTERN)
            when_str = t.strftime("%-I:%M %p ET")
        except Exception:
            when_str = ""
        for side, other in (("home", "away"), ("away", "home")):
            name = g.get(f"{side}GoalieName")
            status = str(
                g.get(f"{side}NewsStrengthName") or g.get(f"{side}NewsStrength") or ""
            ).lower()
            team = g.get(f"{side}TeamName", "?")
            opp = g.get(f"{other}TeamName", "?")
            if name and status == "confirmed":
                key = f"{g.get('gameId', team + opp)}:{side}"
                out[key] = (name, f"{team} vs {opp} {when_str}".strip())
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
    state = {k: v for k, v in state.items() if k.startswith(today)}  # drop old days

    games = fetch_games(today)
    if not games:
        print("No games parsed (off day, or page layout changed — try --debug)")
    for key, (goalie, detail) in extract_alerts(games).items():
        skey = f"{today}:{key}"
        if state.get(skey) != goalie:  # new, or confirmed goalie changed
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
