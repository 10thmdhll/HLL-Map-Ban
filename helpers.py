from datetime import datetime
from typing import List, Tuple
from state import ongoing_events
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