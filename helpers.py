def remaining_combos(ch: int) -> list[tuple[str, str, str]]:
    """
    Return list of (map, faction_order, side) combinations still available for ban.
    """
    from state import channel_teams, ongoing_bans
    return [
        (m, order, side)
        for m, order, side in channel_teams.get(ch, [])
        if m not in ongoing_bans.get(ch, {})
    ]