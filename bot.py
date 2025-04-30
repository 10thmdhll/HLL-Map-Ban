import os
import json
import random
from typing import Literal, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

# ─── Setup ─────────────────────────────────────────────────────────────────────

load_dotenv()
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

STATE_FILE = "state.json"

# In-memory state
ongoing_bans: dict[int, dict[str, dict[str, list[str]]]] = {}
match_turns: dict[int, str] = {}                # "team_a" or "team_b"
channel_teams: dict[int, Tuple[str,str]] = {}   # channel_id → (team_a_name, team_b_name)

# ─── Persistence Helpers ────────────────────────────────────────────────────────

def load_state():
    global ongoing_bans, match_turns, channel_teams
    if not os.path.isfile(STATE_FILE):
        return
    try:
        data = json.load(open(STATE_FILE))
    except json.JSONDecodeError:
        print("⚠️ state.json malformed; resetting state.")
        save_state()
        return

    # reconstruct bans
    raw = data.get("ongoing_bans", {})
    nested = all(
        isinstance(maps, dict) and
        all(isinstance(v, dict) and "team_a" in v and "team_b" in v for v in maps.values())
        for maps in raw.values()
    )
    if not nested:
        print("⚠️ old state format; resetting state.")
        save_state()
        return
    ongoing_bans = {int(ch): maps for ch, maps in raw.items()}

    # reconstruct turns
    match_turns = {int(k): v for k, v in data.get("match_turns", {}).items()}

    # reconstruct channel_teams
    raw_ct = data.get("channel_teams", {})
    channel_teams = {int(ch): tuple(vals) for ch, vals in raw_ct.items()}

def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump({
            "ongoing_bans":  {str(ch): maps for ch, maps in ongoing_bans.items()},
            "match_turns":   {str(k): v for k, v in match_turns.items()},
            "channel_teams": {str(ch): list(vals) for ch, vals in channel_teams.items()}
        }, f, indent=4)

def cleanup_match(ch: int):
    ongoing_bans.pop(ch, None)
    match_turns.pop(ch, None)
    channel_teams.pop(ch, None)
    save_state()
    try:
        os.remove("ban_status.png")
    except FileNotFoundError:
        pass

# ─── Config Loaders ────────────────────────────────────────────────────────────

def load_config():
    return json.load(open("teammap.json"))

def load_maplist():
    return json.load(open("maplist.json"))["maps"]

# ─── Ban-Option & Image Generation ────────────────────────────────────────────

def determine_ban_option(a: str, b: str, cfg: dict) -> str:
    rp = cfg.get("region_pairings", {})
    if a in rp and b in rp[a]:
        return rp[a][b].lower().replace("determinehost","server host")
    return "server host"

def create_ban_status_image(
    map_list: list[dict],
    bans: dict[str, dict[str, list[str]]],
    team_a_label: str,
    team_b_label: str,
    current_turn_label: str|None = None
) -> str:
    cols = [150, 300, 150]
    row_h = 30
    header_h = 40
    banner_h = 30
    width = sum(cols)
    height = banner_h + header_h + len(map_list)*row_h + 20

    img = Image.new("RGB",(width,height),(240,240,240))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except:
        font = ImageFont.load_default()

    # Current-Turn Banner
    if current_turn_label:
        draw.rectangle([0, 0, width, banner_h], fill=(220,220,255))
        draw.text((width/2, banner_h/2),
                  f"Current Turn: {current_turn_label}",
                  font=font, anchor="mm", fill="black")

    # Headers
    labels = [team_a_label, "Maps", team_b_label]
    x0 = 0
    for w, label in zip(cols, labels):
        draw.rectangle([x0, banner_h, x0+w, banner_h+header_h], fill=(200,200,200))
        draw.text((x0 + w/2, banner_h + header_h/2),
                  label, font=font, anchor="mm", fill="black")
        x0 += w

    # Rows
    y = banner_h + header_h
    for m in map_list:
        name = m["name"]
        tb = bans.get(name, {"team_a":[], "team_b":[]})

        def side_for(lst):
            if "Allied" in lst and "Axis" not in lst: return "Axis"
            if "Axis"   in lst and "Allied" not in lst: return "Allies"
            return "Allies"

        a_side = side_for(tb["team_a"])
        b_side = side_for(tb["team_b"])

        def cell_color(side, lst):
            if side in lst: return (255,100,100)
            if len(lst)==1 and side not in lst: return (180,255,180)
            return (255,255,255)

        # Team A
        c0 = cell_color(a_side, tb["team_a"])
        draw.rectangle([0, y, cols[0], y+row_h], fill=c0)
        draw.text((cols[0]/2, y+row_h/2), a_side, font=font, anchor="mm")

        # Map
        draw.rectangle([cols[0], y, cols[0]+cols[1], y+row_h], fill=(240,240,240))
        draw.text((cols[0]+cols[1]/2, y+row_h/2), name, font=font, anchor="mm")

        # Team B
        c2 = cell_color(b_side, tb["team_b"])
        draw.rectangle([cols[0]+cols[1], y, width, y+row_h], fill=c2)
        draw.text((cols[0]+cols[1]+cols[2]/2, y+row_h/2), b_side, font=font, anchor="mm")

        y += row_h

    path = "ban_status.png"
    img.save(path)
    return path

# ─── Autocomplete ──────────────────────────────────────────────────────────────

async def map_autocomplete(interaction: discord.Interaction, current: str):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return []
    team_key = match_turns[ch]
    opts = []
    for m in load_maplist():
        name = m["name"]
        if len(ongoing_bans[ch][name][team_key]) >= 2:
            continue
        if current.lower() in name.lower():
            opts.append(app_commands.Choice(name=name, value=name))
    return opts[:25]

# ─── Slash Commands ────────────────────────────────────────────────────────────

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
            "❌ A match is already active here. Use `/match_delete` first.",
            ephemeral=True
        )
        return

    cfg = load_config()
    maps = load_maplist()
    a, b = team_a.name, team_b.name
    ra, rb = cfg["team_regions"].get(a, "Unknown"), cfg["team_regions"].get(b, "Unknown")
    ban_opt = determine_ban_option(ra, rb, cfg)

    ongoing_bans[ch]  = {m["name"]:{"team_a":[], "team_b":[]} for m in maps}
    match_turns[ch]   = "team_a"
    channel_teams[ch] = (a, b)
    save_state()

    current_label = a
    img = create_ban_status_image(maps, ongoing_bans[ch], a, b, current_label)

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
        await interaction.response.send_message(
            "❌ No active match to delete in this channel.",
            ephemeral=True
        )
        return

    cleanup_match(ch)
    await interaction.response.send_message(
        "✅ Match successfully deleted. You may now `/match_create` again.",
        ephemeral=True
    )

@bot.tree.command(name="ban_map", description="Ban a map side")
@app_commands.autocomplete(map=map_autocomplete)
async def ban_map(
    interaction: discord.Interaction,
    map: str,
    side: Literal["Allied","Axis"]
):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        await interaction.response.send_message(
            "❌ No match here. Run `/match_create` first.",
            ephemeral=True
        )
        return

    team_key = match_turns[ch]
    other_key= "team_b" if team_key=="team_a" else "team_a"
    tbans    = ongoing_bans[ch][map]

    if side in tbans[team_key]:
        await interaction.response.send_message(
            f"❌ {side} already banned by your team.",
            ephemeral=True
        )
        return
    tbans[team_key].append(side)
    tbans[other_key].append("Axis" if side=="Allied" else "Allied")

    match_turns[ch] = other_key
    save_state()

    a_label, b_label = channel_teams.get(ch, ("Team A","Team B"))
    current_label = a_label if match_turns[ch]=="team_a" else b_label
    img = create_ban_status_image(load_maplist(), ongoing_bans[ch],
                                  a_label, b_label, current_label)
    await interaction.response.send_message(file=discord.File(img))

@bot.tree.command(name="show_bans", description="Show current bans")
async def show_bans(interaction: discord.Interaction):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        await interaction.response.send_message(
            "❌ No match active here.", ephemeral=True
        )
        return
    lines = []
    for m in load_maplist():
        tb = ongoing_bans[ch][m["name"]]
        a_bans = ", ".join(tb["team_a"]) or "None"
        b_bans = ", ".join(tb["team_b"]) or "None"
        lines.append(f"**{m['name']}**\nA bans: {a_bans}\nB bans: {b_bans}")
    await interaction.response.send_message("\n\n".join(lines), ephemeral=True)

# ─── Startup ─────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    load_state()
    await bot.tree.sync()
    print("Bot ready as", bot.user)

bot.run(os.getenv("DISCORD_TOKEN"))
