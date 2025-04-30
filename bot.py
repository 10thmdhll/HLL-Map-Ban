import os
import json
import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

# Load environment variables (Discord token)
load_dotenv()
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

STATE_FILE = "state.json"

# In‐memory state:
# ongoing_bans[channel_id][map_name] = {"team_a": [...], "team_b": [...]}
ongoing_bans: dict[int, dict[str, dict[str, list[str]]]] = {}
match_turns: dict[int, str] = {}  # "team_a" or "team_b"

def load_state():
    global ongoing_bans, match_turns
    if not os.path.isfile(STATE_FILE):
        return
    try:
        data = json.load(open(STATE_FILE))
    except json.JSONDecodeError:
        print("⚠️ state.json malformed; resetting.")
        save_state()
        return

    raw = data.get("ongoing_bans", {})
    # ensure new nested format
    nested = all(
        isinstance(maps, dict) and
        all(isinstance(v, dict) and "team_a" in v and "team_b" in v for v in maps.values())
        for maps in raw.values()
    )
    if not nested:
        print("⚠️ old state format; resetting.")
        save_state()
        return

    ongoing_bans = {int(ch): maps for ch, maps in raw.items()}
    match_turns = {int(k): v for k, v in data.get("match_turns", {}).items()}

def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump({
            "ongoing_bans": {str(ch): maps for ch, maps in ongoing_bans.items()},
            "match_turns":  {str(k): v for k, v in match_turns.items()}
        }, f, indent=4)

def load_config():
    return json.load(open("teammap.json"))

def load_maplist():
    return json.load(open("maplist.json"))["maps"]

def determine_ban_option(a: str, b: str, cfg: dict) -> str:
    rp = cfg.get("region_pairings", {})
    if a in rp and b in rp[a]:
        return rp[a][b].lower().replace("determinehost","server host")
    return "server host"

def create_ban_status_image(
    map_list: list[dict],
    bans: dict[str, dict[str, list[str]]],
    host_team: str|None = None,
    current_turn: str|None = None
) -> str:
    # --- Layout parameters ---
    cols = [150, 300, 150]           # widths for [Team A | Maps | Team B]
    row_h =  thirty = 30
    header_h = 40
    width = sum(cols)
    height = header_h + len(map_list)*row_h + 20

    img = Image.new("RGB",(width,height),(240,240,240))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except:
        font = ImageFont.load_default()

    # --- Headers ---
    draw.rectangle([0,0,cols[0],header_h],fill=(200,200,200))
    draw.text((cols[0]//2, header_h//2), "Team A", font=font, anchor="mm", fill="black")
    draw.rectangle([cols[0],0,cols[0]+cols[1],header_h],fill=(200,200,200))
    draw.text((cols[0]+cols[1]//2, header_h//2), "Maps", font=font, anchor="mm", fill="black")
    draw.rectangle([cols[0]+cols[1],0,width,header_h],fill=(200,200,200))
    draw.text((cols[0]+cols[1]+cols[2]//2, header_h//2), "Team B", font=font, anchor="mm", fill="black")

    # --- Rows ---
    y = header_h
    for m in map_list:
        name = m["name"]
        a_bans = bans[name]["team_a"]
        b_bans = bans[name]["team_b"]

        # Decide which side each team will play:
        #  if they've banned Allies → they must play Axis, etc.
        def side_for(team_bans):
            if "Allied" in team_bans and "Axis" not in team_bans:
                return "Axis"
            if "Axis"   in team_bans and "Allied" not in team_bans:
                return "Allies"
            return "Allies"  # default if neither banned

        a_side = side_for(a_bans)
        b_side = side_for(b_bans)

        # Color logic:
        def cell_color(side, team_bans):
            if side in team_bans:
                return (255,100,100)   # red = banned
            # if only one side remains
            if len(team_bans)==1 and side not in team_bans:
                return (180,255,180)   # green = final
            return (255,255,255)       # white = available/default

        # Draw Team A cell
        c0 = cell_color(a_side, a_bans)
        draw.rectangle([0,y,cols[0],y+row_h],fill=c0)
        draw.text((cols[0]//2,y+row_h//2), a_side, font=font, anchor="mm", fill="black")

        # Draw Map name cell
        draw.rectangle([cols[0],y,cols[0]+cols[1],y+row_h],fill=(240,240,240))
        draw.text((cols[0]+cols[1]//2,y+row_h//2), name, font=font, anchor="mm", fill="black")

        # Draw Team B cell
        c2 = cell_color(b_side, b_bans)
        draw.rectangle([cols[0]+cols[1],y,width,y+row_h],fill=c2)
        draw.text((cols[0]+cols[1]+cols[2]//2,y+row_h//2), b_side, font=font, anchor="mm", fill="black")

        y += row_h

    # Save to disk
    path="ban_status.png"
    img.save(path)
    return path

# Autocomplete for maps
async def map_autocomplete(interaction: discord.Interaction, current: str):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return []
    team_key = match_turns[ch]
    opts=[]
    for m in load_maplist():
        name=m["name"]
        if len(ongoing_bans[ch][name][team_key])>=2:
            continue
        if current.lower() in name.lower():
            opts.append(app_commands.Choice(name=name,value=name))
    return opts[:25]

@bot.tree.command(name="match_create", description="Create a new match")
async def match_create(
    interaction: discord.Interaction,
    team_a: discord.Role,
    team_b: discord.Role,
    title: str,
    description: str="No description provided"
):
    ch = interaction.channel_id
    if ch in ongoing_bans and any(
        ongoing_bans[ch][m]["team_a"] or ongoing_bans[ch][m]["team_b"]
        for m in ongoing_bans[ch]
    ):
        await interaction.response.send_message(
            "A match is already active here. Use `/match_delete` first.",
            ephemeral=True
        )
        return

    cfg = load_config()
    maps = load_maplist()
    a,b = team_a.name, team_b.name
    ra,rb = cfg["team_regions"].get(a,"Unknown"), cfg["team_regions"].get(b,"Unknown")
    ban_opt = determine_ban_option(ra,rb,cfg)

    # initialize
    ongoing_bans[ch] = {m["name"]:{"team_a":[],"team_b":[]} for m in maps}
    match_turns[ch]  = "team_a"
    save_state()

    img = create_ban_status_image(maps, ongoing_bans[ch])
    content = (
        f"**Match Created**\n"
        f"Title: {title}\n"
        f"Team A: {a} ({ra})\n"
        f"Team B: {b} ({rb})\n"
        f"Ban Option: {ban_opt}\n"
        f"{description}"
    )
    await interaction.response.send_message(content, file=discord.File(img))

@bot.tree.command(name="match_delete", description="Delete the current match")
async def match_delete(interaction: discord.Interaction):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        await interaction.response.send_message("No active match to delete.", ephemeral=True)
        return
    del ongoing_bans[ch]
    match_turns.pop(ch, None)
    save_state()
    try: os.remove("ban_status.png")
    except: pass
    await interaction.response.send_message("Match deleted; you may `/match_create` again.", ephemeral=True)

@bot.tree.command(name="ban_map", description="Ban a map side")
@app_commands.autocomplete(map=map_autocomplete)
async def ban_map(
    interaction: discord.Interaction,
    map: str,
    side: Literal["Allied","Axis"]
):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        await interaction.response.send_message("No match here. `/match_create` first.", ephemeral=True)
        return

    team_key = match_turns[ch]
    other_key= "team_b" if team_key=="team_a" else "team_a"
    tbans    = ongoing_bans[ch][map]

    if side in tbans[team_key]:
        await interaction.response.send_message(f"{side} already banned.", ephemeral=True)
        return
    tbans[team_key].append(side)

    opp = "Axis" if side=="Allied" else "Allied"
    tbans[other_key].append(opp)

    match_turns[ch] = other_key
    save_state()

    img = create_ban_status_image(load_maplist(), ongoing_bans[ch], current_turn=match_turns[ch])
    await interaction.response.send_message(file=discord.File(img))

@bot.tree.command(name="show_bans", description="Show current bans")
async def show_bans(interaction: discord.Interaction):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        await interaction.response.send_message("No match active here.", ephemeral=True)
        return
    lines=[]
    for m in load_maplist():
        tb = ongoing_bans[ch][m["name"]]
        a_bans=", ".join(tb["team_a"]) or "None"
        b_bans=", ".join(tb["team_b"]) or "None"
        lines.append(f"**{m['name']}**\nA: {a_bans}\nB: {b_bans}")
    await interaction.response.send_message("\n\n".join(lines), ephemeral=True)

@bot.event
async def on_ready():
    load_state()
    await bot.tree.sync()
    print("Bot ready as", bot.user)

bot.run(os.getenv("DISCORD_TOKEN"))
