import json
import discord
from discord import app_commands
from state import load_state, save_state, channel_teams, match_turns, ongoing_bans, channel_mode, channel_decision, match_times

@app_commands.command(name="match_create")
@app_commands.describe(teams="JSON list of (map, order, side) tuples")
async def match_create(interaction: discord.Interaction, teams: str):
    ch = interaction.channel.id
    await load_state(ch)
    channel_teams[ch] = tuple(json.loads(teams))  # e.g. [("map1", "order1", "Allied"), ...]
    match_turns[ch] = []
    ongoing_bans[ch] = {}
    channel_mode[ch] = None
    channel_decision[ch] = None
    match_times[ch] = []
    await save_state(ch)
    await interaction.response.send_message("✅ Match created and initialized.")