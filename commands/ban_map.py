import discord
import asyncio
import helpers
from discord import app_commands
from state import load_state, save_state, ongoing_bans, match_turns, match_times, channel_teams, channel_decision, channel_mode
from helpers import remaining_combos
from datetime import datetime
from typing import List, Tuple, Optional, Literal, Dict, Union

# ─── Autocomplete Handlers ─────────────────────────────────────────────────────
async def map_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Only suggest maps that still have ban slots remaining."""
    ch = interaction.channel_id
    maps = load_maplist()
    choices: List[app_commands.Choice[str]] = []
    for m in maps:
        name = m["name"]
        # filter by input
        if current.lower() not in name.lower():
            continue
        tb = ongoing_bans.get(ch, {}).get(name)
        # if no bans yet, map is available
        if tb is None:
            choices.append(app_commands.Choice(name=name, value=name))
            continue
        # check if any ban slot remains (either team hasn't banned both sides)
        open_slot = False
        for team_key in ("team_a", "team_b"):
            for side in ("Allied", "Axis"):
                if side not in tb[team_key]["manual"] and side not in tb[team_key]["auto"]:
                    open_slot = True
                    break
            if open_slot:
                break
        if open_slot:
            choices.append(app_commands.Choice(name=name, value=name))
    return choices[:50]

async def side_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Only suggest sides still available for the selected map and turn."""
    ch = interaction.channel_id
    sel_map = getattr(interaction.namespace, 'map_name', None)
    if not sel_map or ch not in ongoing_bans:
        return []
    tb = ongoing_bans[ch].get(sel_map, {})
    team_key = match_turns.get(ch)
    if not tb or not team_key:
        return []
    choices: List[app_commands.Choice[str]] = []
    for side in ("Allied", "Axis"):
        if side not in tb[team_key]["manual"] and side not in tb[team_key]["auto"]:
            if current.lower() in side.lower():
                choices.append(app_commands.Choice(name=side, value=side))
    return choices[:50]

@app_commands.command(name="ban_map")
@app_commands.describe(map="Map to ban", side="Side banning map")
async def ban_map(interaction: discord.Interaction, map: str, side: str):
    ch = interaction.channel.id
    await load_state(ch)

    # 1) Must have created a match
    if ch not in channel_teams or not channel_teams[ch]:
        return await interaction.response.send_message(
            "❌ No match created. Use /match_create.", ephemeral=True
        )
    # 2) Coin flip result must exist
    winner = channel_decision.get(ch)
    if not winner:
        return await interaction.response.send_message(
            "❌ Coin flip result missing. Use /match_create.", ephemeral=True
        )
    # 3) Ban mode must be selected
    mode = channel_mode.get(ch)
    if not mode:
        return await interaction.response.send_message(
            "❌ Ban mode not set. Use /select_ban_mode.", ephemeral=True
        )

    # Remaining combos
    rem = remaining_combos(ch)
    # Final vote when only one combo left
    if len(rem) == 1:
        final_map, _, final_side = rem[0]
        if map != final_map or side != final_side:
            return await interaction.response.send_message(
                f"❌ Final vote must be `{final_side}` on `{final_map}`.", ephemeral=True
            )
        ongoing_bans.setdefault(ch, {})[final_map] = final_side
        match_turns.setdefault(ch, []).append(side)
        match_times.setdefault(ch, []).append(datetime.utcnow().isoformat())
        await save_state(ch)
        return await interaction.response.send_message(
            f"🏁 Final vote cast: `{side}` on `{final_map}`.", ephemeral=False
        )

    # Compute loser and turn order
    sides = list({s for _, _, s in channel_teams[ch]})
    loser = sides[1] if sides[0] == winner else sides[0]
    n = len(match_turns.get(ch, []))
    if mode == "final":
        expected = loser if n % 2 == 0 else winner
    else:
        expected = winner if n == 0 else loser if n in (1, 2) else (winner if ((n - 3) % 2 == 0) else loser)

    if side != expected:
        return await interaction.response.send_message(
            f"❌ It's `{expected}`'s turn, not `{side}`.", ephemeral=True
        )

    # Validate availability
    valid = [s for (m, _, s) in rem if m == map]
    if not valid:
        return await interaction.response.send_message(
            f"❌ `{map}` cannot be banned by `{side}`.", ephemeral=True
        )

    # Record normal ban
    ongoing_bans.setdefault(ch, {})[map] = side
    match_turns.setdefault(ch, []).append(side)
    match_times.setdefault(ch, []).append(datetime.utcnow().isoformat())
    await save_state(ch)

    await interaction.response.send_message(f"✅ `{side}` banned `{map}` (Turn {n+1}).")