import discord
from discord import app_commands
from state import load_state, save_state, ongoing_bans, match_turns, match_times, channel_teams, _get_state_file

@app_commands.command(name="match_delete")
async def match_delete(interaction: discord.Interaction):
    """
    Deletes match data (bans, turns, times, teams) but preserves the state file.
    """
    ch = interaction.channel.id
    await load_state(ch)
    # Remove match-specific data
    for var in [ongoing_bans, match_turns, match_times, channel_teams]:
        var.pop(ch, None)
    await save_state(ch)
    await interaction.response.send_message("✅ Match data deleted.")