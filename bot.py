import os
import json
import random
from typing import Literal, Tuple, List

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

# ─── In‐Memory State (persisted across restarts) ───────────────────────────────
ongoing_bans: dict[int, dict[str, dict[str, List[str]]]] = {}
match_turns: dict[int, str] = {}                # "team_a" or "team_b"
channel_teams: dict[int, Tuple[str, str]] = {}  # channel_id → (team_a_name, team_b_name)

# ─── Persistence Helpers ────────────────────────────────────────────────────────
def load_state():
    global ongoing_bans, match_turns, channel_teams
    if not os.path.isfile(STATE_FILE):
        return
    try:
        data = json.load(open(STATE_FILE))
    except json.JSONDecodeError:
        print("⚠️ state.json malformed; overwriting with clean slate")
        save_state()
        return

    # Load ongoing_bans (convert channel keys back to int)
    raw_bans = data.get("ongoing_bans", {})
    ongoing_bans = {int(ch): maps for ch, maps in raw_bans.items()}

    # Load match_turns
    raw_turns = data.get("match_turns", {})
    match_turns = {int(ch): role for ch, role in raw_turns.items()}

    # Load channel_teams
    raw_teams = data.get("channel_teams", {})
    channel_teams = {int(ch): tuple(vals) for ch, vals in raw_teams.items()}

def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump({
            "ongoing_bans":  {str(ch): maps for ch, maps in ongoing_bans.items()},
            "match_turns":   {str(ch): role for ch, role in match_turns.items()},
            "channel_teams": {str(ch): list(vals) for ch, vals in channel_teams.items()}
        }, f, indent=4)

def cleanup_match(ch: int):
    ongoing_bans.pop(ch, None)
    match_turns.pop(ch, None)
    channel_teams.pop(ch, None)
    save_state()
    try: os.remove("ban_status.png")
    except FileNotFoundError: pass

# ─── Config & Maplist Loaders ───────────────────────────────────────────────────
def load_config() -> dict:
    return json.load(open("teammap.json"))

def load_maplist() -> List[dict]:
    return json.load(open("maplist.json"))["maps"]

# ─── Region Pairing & Image Generation ─────────────────────────────────────────
def determine_ban_option(a: str, b: str, cfg: dict) -> str:
    rp = cfg.get("region_pairings", {})
    if a in rp and b in rp[a]:
        return rp[a][b].lower().replace("determinehost", "server host")
    return "server host"

def create_ban_status_image(
    map_list: List[dict],
    bans: dict[str, dict[str, List[str]]],
    team_a_label: str,
    team_b_label: str,
    current_turn_label: str | None = None
) -> str:
    font_size = 18
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    banner_h, header1_h, header2_h, row_h = (
        font_size + 12, font_size + 10, font_size + 8, font_size + 8
    )

    total_w, map_w = 600, 300
    sub_w = (total_w - map_w) // 4
    cols = [sub_w, sub_w, map_w, sub_w, sub_w]
    height = banner_h + header1_h + header2_h + len(map_list) * row_h + 10

    # compute remaining combos
    combos = [
        (name, team, side)
        for name, tb in bans.items()
        for team in ("team_a", "team_b")
        for side in ("Allied", "Axis")
        if side not in tb[team]["manual"] and side not in tb[team]["auto"]
    ]
    final_combo = None
    if len(combos) == 2 and combos[0][0] == combos[1][0]:
        final_combo = combos

    img = Image.new("RGB", (total_w, height), (240, 240, 240))
    draw = ImageDraw.Draw(img)

    # Banner
    y = 0
    if current_turn_label:
        draw.rectangle([0, y, total_w, y+banner_h], fill=(220,220,255), outline="black")
        draw.text(
            (total_w//2, y+banner_h//2),
            f"Current Turn: {current_turn_label}",
            font=font, anchor="mm", fill="black"
        )
    y += banner_h

    # Header row 1
    draw.rectangle([0, y, 2*sub_w, y+header1_h], fill=(200,200,200), outline="black")
    draw.text((sub_w, y+header1_h//2), team_a_label, font=font, anchor="mm", fill="black")
    draw.rectangle([2*sub_w, y, 2*sub_w+map_w, y+header1_h], fill=(200,200,200), outline="black")
    draw.text((2*sub_w+map_w//2, y+header1_h//2), "Maps", font=font, anchor="mm", fill="black")
    draw.rectangle([2*sub_w+map_w, y, total_w, y+header1_h], fill=(200,200,200), outline="black")
    draw.text((2*sub_w+map_w+sub_w, y+header1_h//2), team_b_label, font=font, anchor="mm", fill="black")
    y += header1_h

    # Header row 2
    labels = ["Allied","Axis","","Allied","Axis"]
    x = 0
    for w, lab in zip(cols, labels):
        draw.rectangle([x, y, x+w, y+header2_h], fill=(220,220,220), outline="black")
        if lab:
            draw.text((x+w//2, y+header2_h//2), lab, font=font, anchor="mm", fill="black")
        x += w
    y += header2_h

    # Rows
    for m in map_list:
        name = m["name"]
        tb = bans.get(name, {"team_a":{"manual":[],"auto":[]}, "team_b":{"manual":[],"auto":[]}})
        x = 0
        # Team A
        for side in ("Allied","Axis"):
            if final_combo and (name, "team_a", side) in final_combo:
                c = (180,255,180)
            elif side in tb["team_a"]["manual"]:
                c = (255,0,0)
            elif side in tb["team_a"]["auto"]:
                c = (255,165,0)
            else:
                c = (255,255,255)
            draw.rectangle([x,y,x+sub_w,y+row_h], fill=c, outline="black")
            draw.text((x+sub_w//2, y+row_h//2), side, font=font, anchor="mm", fill="black")
            x += sub_w

        # Map cell
        draw.rectangle([x,y,x+map_w,y+row_h], fill=(240,240,240), outline="black")
        draw.text((x+map_w//2, y+row_h//2), name, font=font, anchor="mm", fill="black")
        x += map_w

        # Team B
        for side in ("Allied","Axis"):
            if final_combo and (name, "team_b", side) in final_combo:
                c = (180,255,180)
            elif side in tb["team_b"]["manual"]:
                c = (255,0,0)
            elif side in tb["team_b"]["auto"]:
                c = (255,165,0)
            else:
                c = (255,255,255)
            draw.rectangle([x,y,x+sub_w,y+row_h], fill=c, outline="black")
            draw.text((x+sub_w//2, y+row_h//2), side, font=font, anchor="mm", fill="black")
            x += sub_w

        y += row_h

    path = "ban_status.png"
    img.save(path)
    return path

# ─── Autocomplete for map based on availability ────────────────────────────────
async def map_autocomplete(interaction: discord.Interaction, current: str):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return []
    team = match_turns[ch]
    choices = []
    for m in load_maplist():
        name = m["name"]
        tb = ongoing_bans[ch][name][team]
        if len(tb["manual"]) + len(tb["auto"]) >= 2:
            continue
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=name))
    return choices[:25]

# ─── Autocomplete for side based on selected map ──────────────────────────────
async def side_autocomplete(interaction: discord.Interaction, current: str):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return []
    selected_map = interaction.namespace.map_name
    team = match_turns[ch]
    tb = ongoing_bans[ch][selected_map][team]
    choices = []
    for side in ("Allied","Axis"):
        if side in tb["manual"] or side in tb["auto"]:
            continue
        if current.lower() in side.lower():
            choices.append(app_commands.Choice(name=side, value=side))
    return choices[:25]

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
    if ch in ongoing_bans:
        await interaction.response.send_message(
            "❌ A match is already active here. Use `/match_delete` first.",
            ephemeral=True
        )
        return

    cfg = load_config()
    maps = load_maplist()
    a, b = team_a.name, team_b.name
    ra, rb = cfg["team_regions"].get(a,"Unknown"), cfg["team_regions"].get(b,"Unknown")
    ban_opt = determine_ban_option(ra, rb, cfg)

    ongoing_bans[ch] = {
        m["name"]: {
            "team_a": {"manual": [], "auto": []},
            "team_b": {"manual": [], "auto": []}
        } for m in maps
    }
    match_turns[ch]   = "team_a"
    channel_teams[ch] = (a, b)
    save_state()

    current_label = a
    img = create_ban_status_image(maps, ongoing_bans[ch], a, b, current_label)
    await interaction.response.send_message(
        f"**Match Created**\nTitle: {title}\nTeam A: {a} ({ra})\nTeam B: {b} ({rb})\nBan Option: {ban_opt}\n{description}",
        file=discord.File(img)
    )

@bot.tree.command(name="match_delete", description="Delete the current match")
async def match_delete(interaction: discord.Interaction):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        await interaction.response.send_message("❌ No active match to delete.", ephemeral=True)
        return
    cleanup_match(ch)
    await interaction.response.send_message("✅ Match deleted.", ephemeral=True)

@app_commands.autocomplete(map_name=map_autocomplete, side=side_autocomplete)
@bot.tree.command(name="ban_map", description="Ban a map side")
async def ban_map(
    interaction: discord.Interaction,
    map_name: str,
    side: str
):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        await interaction.response.send_message("❌ No match here. Run `/match_create` first.", ephemeral=True)
        return

    # if final reached, just display
    combos_pre = [
        (n,t,s)
        for n,tb in ongoing_bans[ch].items()
        for t in ("team_a","team_b")
        for s in ("Allied","Axis")
        if s not in tb[t]["manual"] and s not in tb[t]["auto"]
    ]
    if len(combos_pre)==2 and combos_pre[0][0]==combos_pre[1][0]:
        img = create_ban_status_image(load_maplist(), ongoing_bans[ch],
                                      *channel_teams[ch], None)
        m, t1, s1 = combos_pre[0]; _, t2, s2 = combos_pre[1]
        team1 = channel_teams[ch][0] if t1=="team_a" else channel_teams[ch][1]
        team2 = channel_teams[ch][0] if t2=="team_a" else channel_teams[ch][1]
        await interaction.response.send_message(
            f"🏁 Ban complete!\n- Map: {m}\n- {team1} = {s1}\n- {team2} = {s2}",
            file=discord.File(img)
        )
        return

    # apply ban
    team_key  = match_turns[ch]
    other_key = "team_b" if team_key=="team_a" else "team_a"
    tb = ongoing_bans[ch][map_name]
    tb[team_key]["manual"].append(side)
    opp = "Axis" if side=="Allied" else "Allied"
    tb[other_key]["auto"].append(opp)

    match_turns[ch] = other_key
    save_state()

    # post-ban check
    combos_post = [
        (n,t,s)
        for n,tb in ongoing_bans[ch].items()
        for t in ("team_a","team_b")
        for s in ("Allied","Axis")
        if s not in tb[t]["manual"] and s not in tb[t]["auto"]
    ]
    a_label, b_label = channel_teams[ch]
    current_label = a_label if match_turns[ch]=="team_a" else b_label
    img = create_ban_status_image(load_maplist(), ongoing_bans[ch], a_label, b_label, current_label)

    if len(combos_post)==2 and combos_post[0][0]==combos_post[1][0]:
        m, t1, s1 = combos_post[0]; _, t2, s2 = combos_post[1]
        team1 = a_label if t1=="team_a" else b_label
        team2 = a_label if t2=="team_a" else b_label
        await interaction.response.send_message(
            f"🏁 Ban complete!\n- Map: {m}\n- {team1} = {s1}\n- {team2} = {s2}",
            file=discord.File(img)
        )
    else:
        await interaction.response.send_message(file=discord.File(img))

@bot.tree.command(name="show_bans", description="Show current bans")
async def show_bans(interaction: discord.Interaction):
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        await interaction.response.send_message("❌ No match active here.", ephemeral=True)
        return
    lines = []
    for m in load_maplist():
        tb = ongoing_bans[ch][m["name"]]
        lines.append(
            f"**{m['name']}**\n"
            f"A manual: {', '.join(tb['team_a']['manual']) or 'None'}\n"
            f"A auto: {', '.join(tb['team_a']['auto']) or 'None'}\n"
            f"B manual: {', '.join(tb['team_b']['manual']) or 'None'}\n"
            f"B auto: {', '.join(tb['team_b']['auto']) or 'None'}"
        )
    await interaction.response.send_message("\n\n".join(lines), ephemeral=True)

# ─── Startup ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    load_state()
    print("🔄 Loaded state for channels:", list(ongoing_bans.keys()))
    await bot.tree.sync()
    print("Bot ready as", bot.user)

bot.run(os.getenv("DISCORD_TOKEN"))
