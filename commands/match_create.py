import json
import discord
import asyncio
import random
import helpers
from discord import app_commands
from state import load_state, save_state, channel_teams, match_turns, ongoing_bans, channel_mode, channel_decision, match_times
from PIL import Image, ImageDraw, ImageFont
from typing import List, Tuple, Optional, Literal, Dict, Union

def load_teammap() -> dict:
    with open(CONFIG["teammap_file"]) as f:
        return json.load(f)

def load_maplist() -> List[dict]:
    with open(CONFIG["maplist_file"]) as f:
        return json.load(f)["maps"]

def determine_ban_option(
    a: str,
    b: str,
    cfg: dict
) -> str:
    """
    Determine ban option based on two inputs (team names or region codes) and a config.
    Config should have:
      - "team_regions": mapping team names to region codes
      - "region_pairings": nested mapping regionA -> regionB -> mode
    """
    team_regions = cfg.get("team_regions", {})
    # convert team names to region codes if needed
    region_a = team_regions.get(a, a)
    region_b = team_regions.get(b, b)
    pairings = cfg.get("region_pairings", {})
    # try direct pairing
    option = pairings.get(region_a, {}).get(region_b)
    if option:
        return option
    # try reverse pairing
    return pairings.get(region_b, {}).get(region_a, "ExtraBan")

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