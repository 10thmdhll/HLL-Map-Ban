import os
import json
import asyncio
import logging

logger = logging.getLogger(__name__)

# Directory for per-channel state files
STATE_DIR = "state"
os.makedirs(STATE_DIR, exist_ok=True)

# In-memory state containers
state_locks: dict[int, asyncio.Lock] = {}
going_events: dict[int, dict] = {}


def _state_file(channel_id: int) -> str:
    """Return the path to this channel's state file."""
    return os.path.join(STATE_DIR, f"state_{channel_id}.json")

async def load_state(channel_id: int) -> None:
    lock = state_locks.setdefault(channel_id, asyncio.Lock())
    async with lock:
        path = _state_file(channel_id)
        if not os.path.exists(path):
            ongoing_events[channel_id] = {}
            return
        try:
            with open(path, 'r') as f:
                ongoing_events[channel_id] = json.load(f)
        except json.JSONDecodeError as e:
            logger.warning("Corrupted JSON in %s: %s", path, e)
            ongoing_events[channel_id] = {}

async def save_state(channel_id: int) -> None:
    lock = state_locks.setdefault(channel_id, asyncio.Lock())
    async with lock:
        path = _state_file(channel_id)
        temp = path + ".tmp"
        with open(temp, 'w') as f:
            json.dump(ongoing_events.get(channel_id, {}), f, indent=2)
        os.replace(temp, path)


def list_state_files() -> list[str]:
    """Return all state file paths."""
    return [os.path.join(STATE_DIR, fname)
            for fname in os.listdir(STATE_DIR)
            if fname.startswith("state_") and fname.endswith(".json")]