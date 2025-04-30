import os
import json
import random
import uuid
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

# Load environment variables (for Discord token)
load_dotenv()

# Intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)

# In-memory match state keyed by channel.id
ongoing_bans: dict[int, dict[str, list[str]]] = {}
match_turns: dict[int, str] = {}  # "team_a" or "team_b"

# Load static configs
def load_config():
    with open('teammap.json', 'r') as f:
        return json.load(f)

def load_maplist():
    with open('maplist.json', 'r') as f:
        return json.load(f)['maps']

# Generate the ban status image
def create_ban_status_image(
    map_list: list[dict],
    bans: dict[str, list[str]],
    host_team: str|None=None,
    final_map: str|None=None,
    current_turn: str|None=None
) -> str:
    width, height = 600, len(map_list)*50 + 120
    img = Image.new('RGB',(width,height),(255,255,255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('arial.ttf',20)
    except:
        font = ImageFont.load_default()

    draw.text((20,10),'Map Ban Status',font=font,fill='black')
    y = 50
    for m in map_list:
        name = m['name']
        b = bans.get(name, [])
        allied = 'Allied' in b
        axis   = 'Axis' in b
        if allied and axis:
            bg = (255,0,0)
        elif allied or axis:
            bg = (255,0,0)
        else:
            bg = (0,255,0) if final_map == name else (255,255,255)
        draw.rectangle([20,y,width-20,y+40],fill=bg)
        status = f"{name} | Allied: {'X' if allied else '✓'} / Axis: {'X' if axis else '✓'}"
        draw.text((30,y+10),status,font=font,fill='black')
        y += 50

    if host_team:
        draw.text((20,y+10),f"Host Team: {host_team}",font=font,fill='green')
    if current_turn:
        draw.text((20,y+40),f"Current turn: {current_turn}",font=font,fill='blue')

    path = 'ban_status.png'
    img.save(path)
    return path

# Autocomplete for maps
async def map_autocomplete(interaction: discord.Interaction, current: str):
    channel_id = interaction.channel_id
    bans = ongoing_bans.get(channel_id, {})
    choices = []
    for m in load_maplist():
        name = m['name']
        if len(bans.get(name, [])) >= 2:
            continue
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=name))
    return choices[:25]

# Helper: determine ban option
def determine_ban_option(a: str, b: str, cfg: dict) -> str:
    rp = cfg['region_pairings']
    if a in rp and b in rp[a]:
        return rp[a][b].lower().replace('determinehost','server host')
    return "server host"

# /match_create
@bot.tree.command(name="match_create", description="Create a new match")
async def match_create(
    interaction: discord.Interaction,
    team_a: discord.Role,
    team_b: discord.Role,
    title: str,
    description: str = "No description provided"
):
    cfg = load_config()
    a, b = team_a.name, team_b.name
    ra = cfg['team_regions'].get(a, 'Unknown')
    rb = cfg['team_regions'].get(b, 'Unknown')
    ban_option = determine_ban_option(ra, rb, cfg)

    channel_id = interaction.channel_id
    ongoing_bans[channel_id] = {m['name']: [] for m in load_maplist()}
    match_turns[channel_id] = 'team_a'

    # Generate and send initial image
    img_path = create_ban_status_image(load_maplist(), ongoing_bans[channel_id], host_team=None)
    content = (
        f"**Match Created**\n"
        f"Title: {title}\n"
        f"Team A: {a} ({ra})\n"
        f"Team B: {b} ({rb})\n"
        f"Ban Option: {ban_option}\n"
        f"Description: {description}"
    )
    await interaction.response.send_message(content, file=discord.File(img_path))

# /ban_map
@bot.tree.command(name="ban_map", description="Ban a map side")
@app_commands.autocomplete(map=map_autocomplete)
async def ban_map(
    interaction: discord.Interaction,
    map: str,
    side: Literal["Allied", "Axis"]
):
    channel_id = interaction.channel_id
    if channel_id not in ongoing_bans:
        await interaction.response.send_message("No active match here. Use `/match_create` first.", ephemeral=True)
        return

    bans = ongoing_bans[channel_id]
    if side in bans.get(map, []):
        await interaction.response.send_message(f"{side} of {map} already banned.", ephemeral=True)
        return

    # Ban both sides
    other = "Axis" if side == "Allied" else "Allied"
    bans[map].append(side)
    bans[map].append(other)

    # Rotate turn
    turn = match_turns[channel_id]
    match_turns[channel_id] = 'team_b' if turn == 'team_a' else 'team_a'

    # Regenerate and send updated image
    img_path = create_ban_status_image(load_maplist(), bans, current_turn=match_turns[channel_id])
    await interaction.response.send_message(file=discord.File(img_path))

@bot.event
async def on_ready():
    await bot.tree.sync()
    print("Bot is ready as", bot.user)

bot.run(os.getenv('DISCORD_TOKEN'))
