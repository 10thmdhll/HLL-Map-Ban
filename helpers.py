from datetime import datetime
from typing import List, Tuple
from state import ongoing_events

def format_timestamp(ts: str) -> str:
    from datetime import datetime
    dt = datetime.fromisoformat(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    
def remaining_combos(ch: int) -> List[Tuple[str, str, str]]:
    """
    Return list of (map, team_key, side) combinations still available for ban.
    Assumes ongoing_events[ch] stores a dict of maps to {'team_a': {'manual':[], 'auto':[]}, 'team_b': {...}}.
    """
    combos: List[Tuple[str, str, str]] = []
    channel_data = ongoing_events.get(ch, {})
    for m, tb in channel_data.items():
        for team_key in ("team_a", "team_b"):
            team_data = tb.get(team_key, {})
            manual = team_data.get("manual", [])
            auto = team_data.get("auto", [])
            for side in ("Allied", "Axis"):
                if side not in manual and side not in auto:
                    combos.append((m, team_key, side))
    return combos