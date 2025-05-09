import os
import json
import asyncio
from helpers import remaining_combos
from datetime import datetime
from typing import List, Tuple, Optional, Literal, Dict, Union

# ─── Per-channel state containers and locks ─────────────────────────────────────
state_locks: dict[int, asyncio.Lock] = {}
ongoing_bans: dict[int, dict]      = {}
match_turns: dict[int, list]      = {}
match_times: dict[int, list]      = {}
channel_teams: dict[int, tuple]    = {}
channel_messages: dict[int, any]   = {}
channel_flip: dict[int, bool]      = {}
channel_decision: dict[int, any]   = {}
channel_mode: dict[int, str]       = {}
channel_host: dict[int, int]       = {}


def _get_state_file(ch: int) -> str:
    return f"state_{ch}.json"

async def save_state(ch: int) -> None:
    lock = state_locks.setdefault(ch, asyncio.Lock())
    async with lock:
        payload = {
            "ongoing_bans": ongoing_bans.get(ch, {}),
            "match_turns": match_turns.get(ch, []),
            "match_times": match_times.get(ch, []),
            "channel_teams": list(channel_teams.get(ch, [])),
            "channel_messages": channel_messages.get(ch),
            "channel_flip": channel_flip.get(ch),
            "channel_decision": channel_decision.get(ch),
            "channel_mode": channel_mode.get(ch),
            "channel_host": channel_host.get(ch),
        }
        tmp = _get_state_file(ch) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, _get_state_file(ch))

async def load_state(ch: int) -> None:
    lock = state_locks.setdefault(ch, asyncio.Lock())
    async with lock:
        path = _get_state_file(ch)
        if not os.path.isfile(path):
            return
        with open(path) as f:
            data = json.load(f)
        ongoing_bans[ch]     = data.get("ongoing_bans", {})
        match_turns[ch]      = data.get("match_turns", [])
        match_times[ch]      = data.get("match_times", [])
        channel_teams[ch]    = tuple(data.get("channel_teams", []))
        if data.get("channel_messages") is not None:
            channel_messages[ch] = data.get("channel_messages")
        channel_flip[ch]     = data.get("channel_flip")
        channel_decision[ch] = data.get("channel_decision")
        channel_mode[ch]     = data.get("channel_mode")
        channel_host[ch]     = data.get("channel_host")

# Optional helper to list all state files

def list_state_files() -> list[str]:
    return [f for f in os.listdir() if f.startswith("state_") and f.endswith(".json")]