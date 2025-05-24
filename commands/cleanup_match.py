import os
import discord
from discord import app_commands
import state

@app_commands.command(name="cleanup_match")
async def cleanup_match(interaction: discord.Interaction):
    """Clear match state and delete its file."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    state.ongoing_events.pop(channel_id, None)
    try:
        os.remove(state._state_file(channel_id))
    except FileNotFoundError:
        pass
    await interaction.response.send_message("Match state cleaned up.",delete_after=15)