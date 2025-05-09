import os
import json
import discord
import asyncio
import random
import helpers
import state
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
from typing import List, Tuple, Optional, Literal, Dict, Union

# Path to the teammap configuration
TEAMMAP_PATH = os.path.join(os.getcwd(), "teammap.json")

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

@bot.tree.command(name="match_create", description="Start a new map‐ban match")
@app_commands.describe(team_a="Role for Team A", team_b="Role for Team B")
async def match_create(interaction: discord.Interaction, team_a: discord.Role, team_b: discord.Role):

    # Initialize state
    ch = interaction.channel_id
    await load_state(ch)
    
    # 1) Load and validate teammap.json
    try:
        with open(TEAMMAP_PATH) as f:
            data = json.load(f)
        # Expect a list of [map, order, side] entries
        combos = []
        for entry in data:
            if (
                not isinstance(entry, (list, tuple)) or
                len(entry) != 3 or
                not all(isinstance(x, str) for x in entry)
            ):
                raise ValueError(f"Invalid entry in teammap.json: {entry}")
            combos.append(tuple(entry))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        return await interaction.response.send_message(
            f"❌ Failed to load teammap.json: {e}", ephemeral=True
        )
    
    # 2) Store teams and roles in state
    state.channel_teams[ch]    = tuple(combos)
    state.channel_roles[ch]    = (role_a.id, role_b.id)
    state.match_turns[ch]      = []
    state.ongoing_bans[ch]     = {}
    state.channel_mode[ch]     = None
    state.channel_decision[ch] = None
    state.match_times[ch]      = []

    await state.save_state(ch)
    await interaction.response.send_message(
        f"✅ Match initialized. Team A: {role_a.mention}, Team B: {role_b.mention}",
        ephemeral=False
    )