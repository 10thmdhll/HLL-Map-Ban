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

@bot.tree.command(
    name="match_create",
    description="Start a new map‐ban match"
)
@app_commands.describe(
    team_a="Role for Team A",
    team_b="Role for Team B",
)
async def match_create(
    interaction: discord.Interaction,
    team_a:      discord.Role,
    team_b:      discord.Role,
) -> None:
    global team_a_name, team_b_name
    team_a_name, team_b_name = team_a.name, team_b.name

    # Initialize state
    ch = interaction.channel_id
    await load_state(ch)
    
    # Determine mode based on team_regions mapping
    mode_cfg = load_teammap()
    ra = mode_cfg.get("team_regions", {}).get(team_a.name, "Unknown")
    rb = mode_cfg.get("team_regions", {}).get(team_b.name, "Unknown")
    mode = determine_ban_option(ra, rb, mode_cfg)
    
    # Determine coin flip winner
    flip = random.choice(("team_a","team_b"))
    
    # Determine channel host
    chost = ""
    if mode == "DetermineHost":
        chost = "DetermineHost"
    elif mode == "ExtraBan":
        chost = "Middle Ground Rule"
    else:
        chost = "TBD"
    
    channel_teams[ch]    = (team_a.name, team_b.name)
    channel_mode[ch]     = mode
    channel_flip[ch]     = flip
    channel_decision[ch] = None
    match_turns[ch]      = flip
    match_times[ch]      = "Undecided"
    channel_host[ch]     = chost
    ongoing_bans[ch]     = {
        m["name"]: {"team_a":{"manual":[],"auto":[]},"team_b":{"manual":[],"auto":[]}}
        for m in load_maplist()
    }
    
    # Build the image and embed
    buf = create_ban_image_bytes(
        maps=load_maplist(),
        bans=ongoing_bans[ch],
        mode=channel_mode[ch],
        flip_winner=channel_flip[ch],
        host_key=channel_host[ch],
        decision_choice=channel_decision[ch],
        current_turn=match_turns[ch],
        match_time_iso=match_times.get(ch),
        final=False
    )

    # Build status embed
    A, B = team_a_name, team_b_name
    coin_winner = A if flip=="team_a" else B
    host_name  = channel_host[ch]
    
    tm_iso = match_times.get(ch)
    if tm_iso and tm_iso not in ("Undecided", "TBD"):
        try:
            dt = parser.isoparse(tm_iso).astimezone(
                pytz.timezone(CONFIG["user_timezone"])
            )
            tm_str = dt.strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            tm_str = "Undecided"
    else:
        tm_str = "Undecided"
    
    curr_key   = match_turns[ch]
    curr_name  = A if curr_key=="team_a" else B

    embed = discord.Embed(title="Match Status")
    embed.add_field(name="Team A: ",  value=team_a_name,  inline=True)
    embed.add_field(name="Team B: ",  value=team_b_name,  inline=True)
    embed.add_field(name="Flip Winner",  value=coin_winner,  inline=True)
    embed.add_field(name="Map Host",     value=host_name,    inline=True)
    embed.add_field(name="Mode",         value=mode,         inline=True)
    embed.add_field(name="Match Time",   value=tm_str,       inline=True)
    embed.add_field(name="Current Turn", value=curr_name,    inline=True)
    # **One** response: send image + embed, capture message ID
    await interaction.response.send_message(
        file=discord.File(fp=buf, filename=f"ban_status_{ch}.png"),
        embed=embed
    )
    msg = await interaction.original_response()
    channel_messages[ch] = msg.id
    await save_state(ch)