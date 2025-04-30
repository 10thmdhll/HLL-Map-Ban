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

# In‐memory state
# ongoing_bans[channel_id] = {
#     "team_a": { map_name: [sides] },
#     "team_b": { map_name: [sides] }
# }
ongoing_bans: dict[int, dict[str, dict[str, list[str]]]] = {}
match_turns: dict[int, str] = {}  # "team_a" or "team_b"

def load_state():
    global ongoing_bans, match_turns
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        ongoing_bans = {
            int(ch): {
                "team_a": maps["team_a"],
                "team_b": maps["team_b"]
            }
            for ch, maps in data.get("ongoing_bans", {}).items()
        }
        match_turns = {int(k): v for k, v in data.get("match_turns", {}).items()}
    except json.JSONDecodeError:
        print(f"⚠️ Could not parse {STATE_FILE}, resetting state.")
        ongoing_bans = {}
        match_turns = {}
        save_state()

def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump({
            "ongoing_bans": {
                str(ch): {
                    "team_a": maps["team_a"],
                    "team_b": maps["team_b"]
                }
                for ch, maps in ongoing_bans.items()
            },
            "match_turns": {str(k): v for k, v in match_turns.items()}
        }, f, indent=4)

def load_config():
    try:
        with open("teammap.json","r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error parsing teammap.json: {e}")

def load_maplist():
    try:
        with open("maplist.json","r") as f:
            return json.load(f)["maps"]
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error parsing maplist.json: {e}")

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
    width, height = 600, len(map_list)*50 + 100
    img = Image.new("RGB", (width, height), (255,255,255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except:
        font = ImageFont.load_default()

    draw.text((20,10), "Map Ban Status", font=font, fill="black")
    y = 40
    for m in map_list:
        name = m["name"]
        a_bans = bans[name]["team_a"]
        b_bans = bans[name]["team_b"]
        any_bans = set(a_bans + b_bans)
        allied_banned = "Allied" in any_bans
        axis_banned   = "Axis" in any_bans
        bg = (255,0,0) if allied_banned or axis_banned else (255,255,255)
        draw.rectangle([20, y, width-20, y+40], fill=bg)
        status = (
            f"{name} | A bans: {', '.join(a_bans) or 'None'}  "
            f"B bans: {', '.join(b_bans) or 'None'}"
        )
        draw.text((30, y+10), status, font=font, fill="black")
        y += 50

    if host_team:
        draw.text((20,y+10), f"Host: {host_team}", font=font, fill="green")
    if current_turn:
        draw.text((300,y+10), f"Turn: {current_turn}", font=font, fill="blue")

    path = "ban_status.png"
    img.save(path)
    return path

async def map_autocomplete(interaction: discord.Interaction, current: str):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return []
    team_key = match_turns[ch]
    choices = []
    for m in load_maplist():
        name = m["name"]
        # skip if both sides already banned for this team
        if len(ongoing_bans[ch][team_key][name]) >= 2:
            continue
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=name))
    return choices[:25]

@bot.tree.command(name="match_create", description="Create a new match")
async def match_create(
    interaction: discord.Interaction,
    team_a: discord.Role,
    team_b: discord.Role,
    title: str,
    description: str = "No description provided"
):
    ch = interaction.channel_id
    # prevent a second match if one is active
    if ch in ongoing_bans and any(
        ongoing_bans[ch]["team_a"][m] or ongoing_bans[ch]["team_b"][m]
        for m in ongoing_bans[ch]["team_a"]
    ):
        await interaction.response.send_message(
            "A match is already active here. Use `/match_delete` first.",
            ephemeral=True
        )
        return

    try:
        cfg = load_config()
        maps = load_maplist()
    except RuntimeError as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return

    a, b = team_a.name, team_b.name
    ra = cfg["team_regions"].get(a, "Unknown")
    rb = cfg["team_regions"].get(b, "Unknown")
    ban_opt = determine_ban_option(ra, rb, cfg)

    # initialize bans per team per map
    ongoing_bans[ch] = {
        "team_a":  {m["name"]: [] for m in maps},
        "team_b":  {m["name"]: [] for m in maps}
    }
    match_turns[ch] = "team_a"
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
    side: Literal["Allied", "Axis"]
):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        await interaction.response.send_message("No match here. `/match_create` first.", ephemeral=True)
        return

    team_key = match_turns[ch]
    other_key = "team_b" if team_key == "team_a" else "team_a"

    # record this team's ban
    if side in ongoing_bans[ch][team_key][map]:
        await interaction.response.send_message(f"{side} already banned by your team.", ephemeral=True)
        return
    ongoing_bans[ch][team_key][map].append(side)

    # auto‐ban opposite side for other team
    opp = "Axis" if side == "Allied" else "Allied"
    ongoing_bans[ch][other_key][map].append(opp)

    # rotate turn
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
    lines = []
    for m in load_maplist():
        ta = ", ".join(ongoing_bans[ch]["team_a"][m["name"]]) or "None"
        tb = ", ".join(ongoing_bans[ch]["team_b"][m["name"]]) or "None"
        lines.append(f"**{m['name']}**\n • A bans: {ta}\n • B bans: {tb}")
    await interaction.response.send_message("\n\n".join(lines), ephemeral=True)

@bot.event
async def on_ready():
    load_state()
    await bot.tree.sync()
    print("Bot ready as", bot.user)

bot.run(os.getenv("DISCORD_TOKEN"))
