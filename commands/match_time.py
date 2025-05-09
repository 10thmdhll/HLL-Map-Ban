import discord
from discord import app_commands
import state
from helpers import format_timestamp

@app_commands.command(name="match_time")
async def match_time(interaction: discord.Interaction):
    """List all ban timestamps for this match."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.get(channel_id, {})
    bans = ongoing.get("bans", [])
    if not bans:
        return await interaction.response.send_message("No bans recorded.")
    lines = [f"{b['side']} banned {b['map']} at {format_timestamp(b['timestamp'])}" for b in bans]
    await interaction.response.send_message("\n".join(lines))