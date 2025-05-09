import datetime
import discord
from discord import app_commands
import state
from helpers import format_timestamp

@app_commands.command(name="ban_map")
@app_commands.describe(map_name="Map to ban", side="Role name of banning team")
async def ban_map(interaction: discord.Interaction, map_name: str, side: str):
    """Record a map ban with timestamp."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})
    bans = ongoing.setdefault("bans", [])
    ts = datetime.datetime.utcnow().isoformat() + 'Z'
    bans.append({"map": map_name, "side": side, "timestamp": ts})
    ongoing["current_turn_index"] = len(bans) - 1
    await state.save_state(channel_id)
    await interaction.response.send_message(f"{side} banned {map_name} at {format_timestamp(ts)}.")