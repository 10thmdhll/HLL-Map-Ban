import os
import json
import random
import asyncio
from typing import List, Tuple, Optional, Literal, Dict

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from dateutil import parser
import pytz

# ─── Configuration ───────────────────────────────────────────────────────────────
CONFIG = {
    "state_file":    "state.json",
    "teammap_file":  "teammap.json",
    "maplist_file":  "maplist.json",
    "output_image":  "ban_status.png",
    "user_timezone": "America/New_York",
    "max_inline_width": 800,
    "quantize_colors":  64,
    "compress_level":   9,
    "optimize_png":     True,
    "font_size_h":      144,
    "font_size":        128,
    "font_paths": [
        "arialbd.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
}

# ─── In-Memory State ─────────────────────────────────────────────────────────────
# Global team names for current match
team_a_name: Optional[str] = None
team_b_name: Optional[str] = None

ongoing_bans:      dict[int, dict[str, dict[str, List[str]]]] = {}
match_turns:       dict[int, str]                            = {}
match_times:       dict[int, str]                            = {}
channel_teams:     dict[int, Tuple[str, str]]                = {}
channel_messages:  dict[int, int]                            = {}
channel_flip:      dict[int, str]                            = {}
channel_decision:  dict[int, Optional[str]]                  = {}
channel_mode:      dict[int, str]                            = {}
channel_host:      dict[int, str]                            = {}

# ─── Persistence Helpers ────────────────────────────────────────────────────────
STATE_FILE = CONFIG["state_file"]

def load_state() -> None:
    if not os.path.isfile(STATE_FILE):
        return
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return
    ongoing_bans.update({int(k):v for k,v in data.get("ongoing_bans",{}).items()})
    match_turns.update({int(k):v for k,v in data.get("match_turns",{}).items()})
    match_times.update({int(k):v for k,v in data.get("match_times",{}).items()})
    channel_teams.update({int(k):tuple(v) for k,v in data.get("channel_teams",{}).items()})
    channel_messages.update({int(k):v for k,v in data.get("channel_messages",{}).items()})
    channel_flip.update({int(k):v for k,v in data.get("channel_flip",{}).items()})
    channel_decision.update({int(k):v for k,v in data.get("channel_decision",{}).items()})
    channel_mode.update({int(k):v for k,v in data.get("channel_mode",{}).items()})
    channel_host.update({int(k): v for k,v in data.get("channel_host",{}).items()})


def save_state() -> None:
    payload = {
        "ongoing_bans":     {str(k):v for k,v in ongoing_bans.items()},
        "match_turns":      {str(k):v for k,v in match_turns.items()},
        "match_times":      {str(k):v for k,v in match_times.items()},
        "channel_teams":    {str(k):list(v) for k,v in channel_teams.items()},
        "channel_messages": {str(k):v for k,v in channel_messages.items()},
        "channel_flip":     {str(k):v for k,v in channel_flip.items()},
        "channel_decision": {str(k):v for k,v in channel_decision.items()},
        "channel_mode":     {str(k):v for k,v in channel_mode.items()},
        "channel_host": { str(k): v for k,v in channel_host.items() }
    }
    with open(STATE_FILE, "w") as f:
        json.dump(payload, f, indent=2)

# ─── Config Loaders & Helpers ──────────────────────────────────────────────────
def load_teammap() -> dict:
    with open(CONFIG["teammap_file"]) as f:
        return json.load(f)

def load_maplist() -> List[dict]:
    with open(CONFIG["maplist_file"]) as f:
        return json.load(f)["maps"]

def determine_ban_option(a: str, b: str, cfg: dict) -> str:
    return cfg.get("region_pairings", {}).get(a, {}).get(b, "ExtraBan")

def remaining_combos(ch: int) -> List[Tuple[str,str,str]]:
    combos = []
    for m, tb in ongoing_bans.get(ch, {}).items():
        for team_key in ("team_a", "team_b"):
            for side in ("Allied", "Axis"):
                if side not in tb[team_key]["manual"] and side not in tb[team_key]["auto"]:
                    combos.append((m, team_key, side))
    return combos

def is_ban_complete(ch: int) -> bool:
    combos = remaining_combos(ch)
    return len(combos) == 2 and combos[0][0] == combos[1][0]

def create_ban_status_image(
    maps,
    bans,
    mode: str,
    flip_winner: Optional[str],
    host_key: Optional[str],
    decision_choice: Optional[str],
    current_turn: Optional[str],
    match_time_iso: Optional[str] = None,
    final: bool = False
) -> str:
    # — Load fonts with fallback —
    try:
        hdr_font = ImageFont.truetype(CONFIG["font_paths"][0], CONFIG["font_size_h"])
        row_font = ImageFont.truetype(CONFIG["font_paths"][0], CONFIG["font_size"])
    except OSError:
        hdr_font = ImageFont.load_default()
        row_font = ImageFont.load_default()

    # — Prepare banner lines —
    if match_time_iso:
        try:
            dt = parser.isoparse(match_time_iso).astimezone(
                pytz.timezone(CONFIG["user_timezone"])
            )
            dt_str = dt.strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            dt_str = "Undecided"
    else:
        dt_str = "Undecided"
    
    # — Derive display names —
    A = team_a_name or "Team A"
    B = team_b_name or "Team B"
    coin_winner = A if flip_winner == "team_a" else B if flip_winner == "team_b" else "TBD"
    if host_key in ("team_a", "team_b"):
        host = A if host_key == "team_a" else B
    else:
        host = host_key or "TBD"
    current = A if current_turn == "team_a" else B if current_turn == "team_b" else "TBD"
    decision = decision_choice or "None"
    banner1 = f"Coin Flip Winner: {coin_winner} | Decision: {decision}"
    banner2 = f"Host: {host}    |    Match: {dt_str}"
    banner3 = f"Current Turn: {current}"
    
    padding = 20
    line_spacer = 10
    
    # — Measure banner heights —
    dummy = Image.new("RGB", (1,1))
    measure = ImageDraw.Draw(dummy)
    bbox1 = measure.textbbox((0, 0), banner1, font=hdr_font)
    bbox2 = measure.textbbox((0, 0), banner2, font=hdr_font)
    bbox3 = measure.textbbox((0, 0), banner3, font=hdr_font)
    h1 = bbox1[3] - bbox1[1]
    h2 = bbox2[3] - bbox2[1]
    h3 = bbox3[3] - bbox3[1]
    header_h = padding + h1 + line_spacer + h2 + line_spacer + h3 + padding

    # — Grid dimensions —
    rows = len(maps)
    cols = 3  # Team A, Map name, Team B
    total_width = CONFIG["max_inline_width"]
    cell_w = total_width // cols
    row_bbox = measure.textbbox((0,0), "Allied [ ] | Axis [ ]", font=row_font)
    row_h    = (row_bbox[3] - row_bbox[1]) + padding
    img_h = header_h + rows * row_h + padding

    # — Create canvas —
    img = Image.new("RGBA", (total_width + padding*2, img_h), "white")
    draw = ImageDraw.Draw(img)
    
    # — Draw banners —
    y = padding
    draw.text((padding, y), banner1, font=hdr_font, fill="black")
    y += h1 + line_spacer
    draw.text((padding, y), banner2, font=hdr_font, fill="black")
    y += h2 + line_spacer
    draw.text((padding, y), banner3, font=hdr_font, fill="black")

    # — Draw grid rows —
    grid_x0 = padding
    grid_y0 = header_h
    square = "■"
    redx = "❌"
    
    
    for i, m in enumerate(maps):
        name = m["name"]
        y0 = grid_y0 + i * row_h
        # Team A cell
        ta = bans[name]["team_a"]
        a_mark = redx if "Allied" in ta["manual"] or "Allied" in ta["auto"] else "    "
        x_mark = redx if "Axis" in ta["manual"] or "Axis" in ta["auto"] else "    "
        left_text = f"   Allied [{a_mark}]    |    Axis [{x_mark}]   "
        draw.text((grid_x0, y0), left_text, font=row_font, fill="black")

        # Map name cell (centered in middle column)
        mx = grid_x0 + cell_w
        bbox = measure.textbbox((0,0), name, font=row_font)
        w_map = bbox[2] - bbox[0]
        draw.text((mx + (cell_w - w_map)/2, y0), name, font=row_font, fill="black")

        # Team B cell
        tb = bans[name]["team_b"]
        a_mark = redx if "Allied" in tb["manual"] or "Allied" in tb["auto"] else " "
        x_mark = redx if "Axis" in tb["manual"] or "Axis" in tb["auto"] else " "
        right_text = f"    Allied [{a_mark}]   |   Axis [{x_mark}]    "
        rx = grid_x0 + 2*cell_w
        draw.text((rx, y0), right_text, font=row_font, fill="black")

    # — Save and return —
    out_path = os.path.join(os.getcwd(), CONFIG["output_image"])
    img.save(out_path, optimize=True, compress_level=9)
    return out_path

# ─── Messaging Helper ─────────────────────────────────────────────────────────
async def update_status_message(
    channel_id: int,
    message_id: Optional[int],
    image_path: str,
    embed: Optional[discord.Embed] = None
) -> None:
    channel = bot.get_channel(channel_id)
    if message_id:
        try:
            msg = await channel.fetch_message(message_id)
            file = discord.File(image_path, filename=os.path.basename(image_path))
            await msg.edit(files=[file], embed=embed)
        except Exception:
            # fallback: send a fresh message and store its ID
            new = await channel.send(file=discord.File(image_path), embed=embed)
            channel_messages[channel_id] = new.id
            save_state()
    else:
        # no existing message → send new
        new = await channel.send(file=discord.File(image_path), embed=embed)
        channel_messages[channel_id] = new.id
        save_state()

async def delete_later(msg: discord.Message, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass
        
# ─── Bot Setup ─────────────────────────────────────────────────────────────────
load_dotenv()
# Enable necessary intents for slash commands and message content
intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.intents.message_content = True

# ─── Autocomplete Handlers ─────────────────────────────────────────────────────
async def map_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Only suggest maps that still have ban slots remaining."""
    ch = interaction.channel_id
    maps = load_maplist()
    choices: List[app_commands.Choice[str]] = []
    for m in maps:
        name = m["name"]
        # filter by input
        if current.lower() not in name.lower():
            continue
        tb = ongoing_bans.get(ch, {}).get(name)
        # if no bans yet, map is available
        if tb is None:
            choices.append(app_commands.Choice(name=name, value=name))
            continue
        # check if any ban slot remains (either team hasn't banned both sides)
        open_slot = False
        for team_key in ("team_a", "team_b"):
            for side in ("Allied", "Axis"):
                if side not in tb[team_key]["manual"] and side not in tb[team_key]["auto"]:
                    open_slot = True
                    break
            if open_slot:
                break
        if open_slot:
            choices.append(app_commands.Choice(name=name, value=name))
    return choices[:50]

async def side_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Only suggest sides still available for the selected map and turn."""
    ch = interaction.channel_id
    sel_map = getattr(interaction.namespace, 'map_name', None)
    if not sel_map or ch not in ongoing_bans:
        return []
    tb = ongoing_bans[ch].get(sel_map, {})
    team_key = match_turns.get(ch)
    if not tb or not team_key:
        return []
    choices: List[app_commands.Choice[str]] = []
    for side in ("Allied", "Axis"):
        if side not in tb[team_key]["manual"] and side not in tb[team_key]["auto"]:
            if current.lower() in side.lower():
                choices.append(app_commands.Choice(name=side, value=side))
    return choices[:50]

async def cleanup_match(ch: int):
    for d in (
        ongoing_bans, match_turns, channel_teams, match_times,
        channel_messages, channel_flip, channel_decision, channel_mode, channel_host
    ):
        d.pop(ch, None)
    save_state()
    try:
        os.remove(CONFIG["output_image"])
    except FileNotFoundError:
        pass
        
@bot.tree.command(
    name="match_create",
    description="Start a new map‐ban match",
    guild=discord.Object(id=1366830976369557654)
)
@app_commands.describe(
    team_a="Role for Team A",
    team_b="Role for Team B",
)
async def match_create(
    interaction: discord.Interaction,
    title:       str,
    team_a:      discord.Role,
    team_b:      discord.Role,
) -> None:
    global team_a_name, team_b_name
    team_a_name, team_b_name = team_a.name, team_b.name

    # Initialize state
    load_state()
    ch = interaction.channel_id
    
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
    save_state()

    # Build the image and embed
    img = create_ban_status_image(
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

    embed = discord.Embed(title=f"🎲 {title}")
    embed.add_field(name="Flip Winner",  value=coin_winner,  inline=True)
    embed.add_field(name="Map Host",     value=host_name,    inline=True)
    embed.add_field(name="Mode",         value=mode,         inline=True)
    embed.add_field(name="Match Time",   value=tm_str,       inline=True)
    embed.add_field(name="Current Turn", value=curr_name,    inline=True)

    # **One** response: send image + embed, capture message ID
    await interaction.response.send_message(
        file=discord.File(img),
        embed=embed
    )
    msg = await interaction.original_response()
    channel_messages[ch] = msg.id
    save_state()   

@bot.tree.command(
    name="ban_map",
    description="Ban a map for a given side",
    guild=discord.Object(id=1366830976369557654)
)
@app_commands.describe(
    map_name="Map to ban",
    side="Allied or Axis"
)
@app_commands.autocomplete(
    map_name=map_autocomplete,
    side=side_autocomplete
)
async def ban_map(
    interaction: discord.Interaction,
    map_name: str,
    side: str
) -> None:
    ch = interaction.channel_id
    global team_a_name, team_b_name
    team_a_name, team_b_name = channel_teams[ch]

    # 1) Turn check
    if ch not in match_turns:
        return await interaction.response.send_message(
            "❌ No active match in this channel.", ephemeral=True
        )
    current_key = match_turns[ch]  # "team_a" or "team_b"
    # channel_teams[ch] == (team_a_name, team_b_name)
    allowed_role = channel_teams[ch][0] if current_key == "team_a" else channel_teams[ch][1]
    if not any(r.name == allowed_role for r in interaction.user.roles):
        return await interaction.response.send_message(f"❌ It's not your turn to ban.", ephemeral=True)
    
    # 2) Pre‐compute remaining combos
    combos = remaining_combos(ch)
    final_combo = (len(combos) == 2 and combos[0][0] == combos[1][0])

    if final_combo:
        # --- FINAL BRANCH: lock in and send in one shot ---
        tb = ongoing_bans.setdefault(ch, {})
        tb.setdefault(map_name, {"team_a":{"manual":[],"auto":[]},"team_b":{"manual":[],"auto":[]}})
        tk = match_turns[ch]
        #tb[map_name][tk]["manual"].append(side)
        other = "team_b" if tk=="team_a" else "team_a"
        #tb[map_name][other]["auto"].append("Axis" if side=="Allied" else "Allied")
        #match_turns[ch] = other
        save_state()


        img = create_ban_status_image(
            maps=load_maplist(),
            bans=ongoing_bans[ch],
            mode=channel_mode[ch],
            flip_winner=channel_flip[ch],
            host_key=channel_host[ch],
            decision_choice=channel_decision[ch],
            current_turn=match_turns[ch],
            match_time_iso=match_times.get(ch),
            final=True
        )

        # Single acknowledge + edit
        await interaction.response.send_message(
            "✅ Ban phase complete — final map locked.",
            ephemeral=True
        )
        await update_status_message(ch, channel_messages[ch], img)
        return

    # --- NORMAL BRANCH: defer, edit, follow‐up ---
    await interaction.response.defer()

    # record the manual + auto ban, advance turn, save_state…
    tb = ongoing_bans.setdefault(ch, {})
    tb.setdefault(map_name, {"team_a":{"manual":[],"auto":[]},"team_b":{"manual":[],"auto":[]}})
    tk = match_turns[ch]
    tb[map_name][tk]["manual"].append(side)
    other = "team_b" if tk=="team_a" else "team_a"
    tb[map_name][other]["auto"].append("Axis" if side=="Allied" else "Allied")
    match_turns[ch] = other
    save_state()

    img = create_ban_status_image(
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
    
    embed = discord.Embed(title="Match Status")
    embed.add_field(name="Flip Winner",   value=coin_winner,   inline=True)
    embed.add_field(name="Map Host",      value=host_name,     inline=True)
    embed.add_field(name="Mode",          value=mode,          inline=True)
    embed.add_field(name="Match Time",    value=time_str,      inline=True)
    embed.add_field(name="Current Turn",  value=current_name,  inline=True)
    
    await update_status_message(
        ch,
        channel_messages[ch],
        img,
        embed=embed
    )

    # Then confirm privately
    await interaction.followup.send("✅ Updated.", ephemeral=True)
      
@bot.tree.command(
    name="match_time",
    description="Set the scheduled match time",
    guild=discord.Object(id=1366830976369557654)
)
@app_commands.describe(
    time="ISO-8601 datetime (with timezone) for the match -> ex. 2025-05-21T18:00:00-04:00"
)
async def match_time_cmd(
    interaction: discord.Interaction,
    time: str
) -> None:
    ch = interaction.channel_id
    global team_a_name, team_b_name
    team_a_name, team_b_name = channel_teams[ch]

    # 1) Ensure there’s an active match and it’s past ban phase
    if ch not in ongoing_bans or not is_ban_complete(ch):
        return await interaction.response.send_message(
            "❌ Ban phase not complete or no active match.", 
            ephemeral=True
        )

    # 2) Only team members may set the time
    team_roles = channel_teams[ch]
    if not any(r.name in team_roles for r in interaction.user.roles):
        return await interaction.response.send_message(
            "❌ Only players in this match may set the time.", 
            ephemeral=True
        )

    # 3) Acknowledge so we can take our time
    await interaction.response.defer()

    # 4) Parse and store in UTC
    try:
        dt = parser.isoparse(time).astimezone(pytz.utc)
        match_times[ch] = dt.isoformat()
        save_state()
    except Exception as e:
        return await interaction.followup.send(
            f"❌ Invalid datetime: {e}", 
            ephemeral=True
        )

    # 5) Rebuild the image (now with the new time included)
    img = create_ban_status_image(
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

    # 6) Build the status embed
    A = team_a_name; B = team_b_name
    coin_winner = A if channel_flip[ch]=="team_a" else B
    host_name  = channel_host[ch]
    mode       = channel_mode[ch]
    match_time = match_times.get(ch)
    if match_time:
        dt = parser.isoparse(match_time).astimezone(pytz.timezone(CONFIG["user_timezone"]))
        time_str = dt.strftime("%Y-%m-%d %H:%M %Z")
    else:
        time_str = "Undecided"
    current_key = match_turns.get(ch)
    current_name= A if current_key=="team_a" else B

    embed = discord.Embed(title="Match Status")
    embed.add_field(name="Flip Winner",   value=coin_winner,   inline=True)
    embed.add_field(name="Map Host",      value=host_name,     inline=True)
    embed.add_field(name="Mode",          value=mode,          inline=True)
    embed.add_field(name="Match Time",    value=time_str,      inline=True)
    embed.add_field(name="Current Turn",  value=current_name,  inline=True)

    # 7) Edit the original image message with both image + embed
    await update_status_message(
        ch,
        channel_messages[ch],
        img,
        embed=embed
    )

    # Then confirm privately
    await interaction.followup.send("✅ Updated.", ephemeral=True)

    
@bot.tree.command(
    name="match_decide",
    description="Choose whether the flip-winner bans first or hosts first if no Middle Ground Rule",
    guild=discord.Object(id=1366830976369557654)
)
@app_commands.describe(
    choice="If ‘ban’, flip-winner bans first; if ‘host’, flip-winner hosts and other side bans first"
)
async def match_decide(
    interaction: discord.Interaction,
    choice: Literal["ban", "host"]
) -> None:
    ch = interaction.channel_id
    global team_a_name, team_b_name
    team_a_name, team_b_name = channel_teams[ch]

    # 1) Ensure a match exists
    if ch not in channel_messages:
        return await interaction.response.send_message(
            "❌ No active match in this channel.", ephemeral=True
        )

    # 2) Restrict to players in the two teams
    team_roles = channel_teams.get(ch, ())
    if not any(r.name in team_roles for r in interaction.user.roles):
        return await interaction.response.send_message(
            "❌ Only players in this match may decide.", ephemeral=True
        )

    # 3) Acknowledge to allow processing
    await interaction.response.defer()

    # 4) Record the decision
    channel_decision[ch] = choice

    # 5) Compute first-ban turn
    flip_key = channel_flip[ch]  # “team_a” or “team_b”
    if choice == "ban":
        # flip-winner bans first
        match_turns[ch] = flip_key
    else:
        # flip-winner hosts, so the other team bans first
        match_turns[ch] = "team_b" if flip_key == "team_a" else "team_a"

    save_state()

    # 6) Rebuild the updated status image
    img = create_ban_status_image(
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

    # 7) Build the status embed
    A = team_a_name; B = team_b_name
    coin_winner = A if channel_flip[ch]=="team_a" else B
    host_name  = channel_host[ch]
    mode       = channel_mode[ch]
    match_time = match_times.get(ch)
    if match_time:
        dt = parser.isoparse(match_time).astimezone(pytz.timezone(CONFIG["user_timezone"]))
        time_str = dt.strftime("%Y-%m-%d %H:%M %Z")
    else:
        time_str = "None"
    current_key = match_turns.get(ch)
    current_name= A if current_key=="team_a" else B

    embed = discord.Embed(title="Match Status")
    embed.add_field(name="Flip Winner",   value=coin_winner,   inline=True)
    embed.add_field(name="Map Host",      value=host_name,     inline=True)
    embed.add_field(name="Mode",          value=mode,          inline=True)
    embed.add_field(name="Match Time",    value=time_str,      inline=True)
    embed.add_field(name="Current Turn",  value=current_name,  inline=True)

    # 8) Edit the original image message with both image + embed
    await update_status_message(
        ch,
        channel_messages[ch],
        img,
        embed=embed
    )

    # Then confirm privately
    await interaction.followup.send("✅ Updated.", ephemeral=True)


@bot.tree.command(
    name="match_delete",
    description="End and remove the current match",
    guild=discord.Object(id=1366830976369557654)
)
async def match_delete(interaction: discord.Interaction) -> None:
    ch = interaction.channel_id

    # 1) Ensure there’s an active match
    if ch not in channel_messages:
        return await interaction.response.send_message(
            "❌ No active match to delete in this channel.", ephemeral=True
        )

    # 2) Restrict to participants of this match
    #team_roles = channel_teams.get(ch, ())
    #if not any(r.name in team_roles for r in interaction.user.roles):
    #    return await interaction.response.send_message(
    #        "❌ Only participants of this match may delete it.", ephemeral=True
    #    )

    # 3) Acknowledge to allow I/O
    await interaction.response.defer()

    # 4) Delete the original match image message
    msg_id = channel_messages.get(ch)
    if msg_id:
        try:
            channel = bot.get_channel(ch)
            msg = await channel.fetch_message(msg_id)
            await msg.delete()
        except Exception:
            pass  # ignore if already deleted or missing

    # 5) Clear all per‐channel state and persist
    for state_dict in (
        ongoing_bans,
        match_turns,
        match_times,
        channel_teams,
        channel_messages,
        channel_flip,
        channel_decision,
        channel_mode,
        channel_host
    ):
        state_dict.pop(ch, None)
    save_state()

    # 6) Confirm deletion to the user
    await interaction.followup.send(
        "✅ Match has been deleted and state cleared.", 
        ephemeral=True
    )

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: Exception
) -> None:
    if isinstance(error, discord.errors.NotFound):
        return
    raise error

# ─── Ready & Sync ─────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    # Load/persist state as you already have…
    guild = discord.Object(id=1366830976369557654)
    synced = await bot.tree.sync(guild=guild)
    print(f"Synced {len(synced)} commands to guild {guild.id}: {[c.name for c in synced]}")
    print("Bot is ready.")
    load_state()

bot.run(os.getenv("DISCORD_TOKEN"))