import os
import discord
from discord import app_commands
from state import load_state, channel_teams, ongoing_bans, match_turns, match_times, channel_messages, channel_flip, channel_decision, channel_mode, channel_host
from state import _get_state_file

@app_commands.command(name="cleanup_match")
async def cleanup_match(interaction: discord.Interaction):
    ch = interaction.channel.id
    await load_state(ch)
    for var in [ongoing_bans, match_turns, match_times, channel_teams,
                channel_messages, channel_flip, channel_decision, channel_mode, channel_host]:
        var.pop(ch, None)
    try:
        os.remove(_get_state_file(ch))
    except FileNotFoundError:
        pass
    await interaction.response.send_message("✅ Match state cleaned up.")