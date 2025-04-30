import os
import json
import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

# Load env
load_dotenv()
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

STATE_FILE = "state.json"

# In‐memory state:
# ongoing_bans[channel_id] = {
#   "team_a": { map_name: [sides...] },
#   "team_b": { map_name: [sides...] }
# }
ongoing_bans: dict[int, dict[str, dict[str, list[str]]]] = {}
match_turns: dict[int, str] = {}  # either "team_a" or "team_b"

def load_state():
    global ongoing_bans, match_turns
    if not os.path.isfile(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print("⚠️ state.json malformed; resetting state.")
        save_state()
        return

    raw = data.get("ongoing_bans", {})
    # detect nested-per-team
    nested = True
    for maps in raw.values():
        if not isinstance(maps, dict) or "team_a" not in maps or "team_b" not in maps:
            nested = False
            break
    if not nested:
        print("⚠️ old state format; resetting state.")
        save_state()
        return

    ongoing_bans = {
        int(ch): {
            "team_a": maps["team_a"],
            "team_b": maps["team_b"]
        }
        for ch, maps in raw.items()
    }
    match_turns = {int(k): v for k, v in data.get("match_turns", {}).items()}

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
    with open("teammap.json", "r") as f:
        return json.load(f)

def load_maplist():
    with open("maplist.json", "r") as f:
        return json.load(f)["maps"]

def determine_ban_option(a: str, b: str, cfg: dict) -> str:
    rp = cfg.get("region_pairings", {})
    if a in rp and b in rp[a]:
        return rp[a][b].lower().replace("determinehost", "server host")
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
        team_a_bans = bans.get(name, {}).get("team_a", [])
        team_b_bans = bans.get(name, {}).get("team_b", [])
        combined = set(team_a_bans + team_b_bans)
        allied_banned = "Allied" in combined
        axis_banned   = "Axis" in combined
        bg = (255,0,0) if allied_banned or axis_banned else (255,255,255)
        draw.rectangle([20, y, width-20, y+40], fill=bg)
        status = (
            f"{name} | A bans: {', '.join(team_a_bans) or 'None'}  "
            f"B bans: {', '.join(team_b_bans) or 'None'}"
        )
        draw.text((30, y+10), status, font=font, fill="black")
        y += 50

    if host_team:
        draw.text((20, y+10), f"Host: {host_team}", font=font, fill="green")
    if current_turn:
        draw.text((300, y+10), f"Turn: {current_turn}", font=font, fill="blue")

    path = "ban_status.png"
    img.save(path)
    return path

async def map_autocomplete(interaction: discord.Interaction, current: str):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return []
    team_key = match_turns.get(ch, "team_a")
    choices = []
    for m in load_maplist():
        name = m["name"]
        banned = ongoing_bans[ch].get(name, {}).get(team_key, [])
        if len(banned) >= 2:
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
    # Prevent duplicate matches
    if ch in ongoing_bans and any(
        ongoing_bans[ch].get(m, {}).get("team_a", []) or ongoing_bans[ch].get(m, {}).get("team_b", [])
        for m in ongoing_bans[ch]
    ):
        await interaction.response.send_message(
            "A match is already active here. Use `/match_delete` first.",
            ephemeral=True
        )
        return

    try:
        cfg = load_config()
        maps = load_maplist()
    except Exception as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return

    a, b = team_a.name, team_b.name
    ra = cfg["team_regions"].get(a, "Unknown")
    rb = cfg["team_regions"].get(b, "Unknown")
    ban_opt = determine_ban_option(ra, rb, cfg)

    # Initialize per-team bans
    ongoing_bans[ch] = {
        m["name"]: {"team_a": [], "team_b": []}
        for m in maps
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
    try:
        os.remove("ban_status.png")
    except:
        pass
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

    team_key = match_turns.get(ch, "team_a")
    other_key = "team_b" if team_key == "team_a" else "team_a"

    # record ban for this team
    team_bans = ongoing_bans[ch].setdefault(map, {"team_a": [], "team_b": []})
    if side in team_bans[team_key]:
        await interaction.response.send_message(f"{side} already banned by your team.", ephemeral=True)
        return
    team_bans[team_key].append(side)

    # auto‐ban opposite side for other team
    opp = "Axis" if side == "Allied" else "Allied"
    team_bans[other_key].append(opp)

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
        tb = ongoing_bans[ch].get(m["name"], {})
        a_bans = ", ".join(tb.get("team_a", [])) or "None"
        b_bans = ", ".join(tb.get("team_b", [])) or "None"
        lines.append(f"**{m['name']}**\n • A bans: {a_bans}\n • B bans: {b_bans}")
    await interaction.response.send_message("\n\n".join(lines), ephemeral=True)

@bot.event
async def on_ready():
    load_state()
    await bot.tree.sync()
    print("Bot ready as", bot.user)

bot.run(os.getenv("DISCORD_TOKEN"))
