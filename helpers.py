from datetime import datetime
from typing import List, Tuple
import state
import discord
from discord import TextChannel

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
    
async def update_host_mode_choice_embed(channel: discord.TextChannel, message_id: int, new_choice: str):
    # 1) Fetch the bot’s original embed message
    msg = await channel.fetch_message(message_id)
    if not msg.embeds:
        raise RuntimeError("No embed found on that message")

    # 2) Clone the existing embed
    embed = msg.embeds[0]
    
    # 3) Find the index of the field you want to update
    field_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Host Mode Choice"),
        None
    )
    if field_index is None:
        # If it doesn’t exist yet, append it instead
        embed.add_field(name="Host Mode Choice", value=new_choice, inline=False)
    else:
        # 4) Mutate that field in-place
        embed.set_field_at(field_index, name="Host Mode Choice", value=new_choice, inline=False)

    # 5) Push the edit back to Discord
    await msg.edit(embed=embed)
    
async def update_ban_mode_choice_embed(channel: discord.TextChannel, message_id: int, new_choice: str):
    # 1) Fetch the bot’s original embed message
    msg = await channel.fetch_message(message_id)
    if not msg.embeds:
        raise RuntimeError("No embed found on that message")

    # 2) Clone the existing embed
    embed = msg.embeds[0]
    
    # 3) Find the index of the field you want to update
    field_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Ban Mode"),
        None
    )
    if field_index is None:
        # If it doesn’t exist yet, append it instead
        embed.add_field(name="Ban Mode", value=new_choice, inline=True)
    else:
        # 4) Mutate that field in-place
        embed.set_field_at(field_index, name="Ban Mode", value=new_choice, inline=True)

    # 5) Push the edit back to Discord
    await msg.edit(embed=embed)
    
async def flip_turn(channel_id: int) -> int:
    """
    Advance the current_turn_index to the next team (wraps around),
    save state, and return the new turn index.
    """
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})

    teams = ongoing.get("teams", [])
    if len(teams) < 2:
        raise RuntimeError("Cannot flip turn: 'teams' is not set or has fewer than 2 entries")

    current = ongoing.get("current_turn_index", 0)
    new_turn = (current + 1) % len(teams)
    ongoing["current_turn_index"] = new_turn

    # ─── Safely append to update_history ─────────────────────────────────
    history = ongoing.get("update_history")
    if not isinstance(history, list):
        history = []
    history.append({
        "event": "turn_flipped",
        "new_turn_index": new_turn,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })
    ongoing["update_history"] = history

    await state.save_state(channel_id)
    return new_turn
    
async def update_current_turn_embed(
    channel: discord.TextChannel,
    message_id: int,
    new_turn_index: int
) -> None:
    """
    Fetch the existing status embed by message_id, find the 'Current Turn' field,
    and update it to point to the correct team role mention.
    """
    # Load the latest state to resolve which role ID corresponds to this turn
    await state.load_state(channel.id)
    ongoing = state.ongoing_events[channel.id]
    teams = ongoing.get("teams", [])
    if new_turn_index >= len(teams):
        return  # sanity check

    next_role_id = teams[new_turn_index]

    # Fetch and edit the embed
    msg = await channel.fetch_message(message_id)
    if not msg.embeds:
        raise RuntimeError("No embed found on that message")

    embed = msg.embeds[0]
    # Find or append the 'Current Turn' field
    idx = next((i for i,f in enumerate(embed.fields) if f.name == "Current Turn:"), None)
    mention = f"<@&{next_role_id}>"
    if idx is None:
        embed.add_field(name="Current Turn:", value=mention, inline=False)
    else:
        embed.set_field_at(idx, name="Current Turn:", value=mention, inline=False)

    await msg.edit(embed=embed)