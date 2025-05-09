"""
Shared utility functions.
"""

def format_timestamp(ts: str) -> str:
    """Convert ISO timestamp to human-readable form."""
    from datetime import datetime
    dt = datetime.fromisoformat(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")