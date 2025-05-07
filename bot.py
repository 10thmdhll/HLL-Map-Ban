import os
import json
import random
import asyncio
from typing import List, Tuple, Optional, Literal, Dict, Union
from io import BytesIO
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from dateutil import parser
import pytz
import glob, tempfile

# ─── Configuration ───────────────────────────────────────────────────────────────
CONFIG = {
    "state_file":    "state.json",
    "teammap_file":  "teammap.json",
    "maplist_file":  "maplist.json",
    "output_image":  "ban_status.png",
    "user_timezone": "America/New_York",
    "max_inline_width": 800,
    "font_size_h":      36,
    "font_size":        24,
    "font_paths": [
        "arialbd.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
}

# ─── Preload fonts once ─────────────────────────────────────────────────────────
font_file = next((p for p in CONFIG["font_paths"] if os.path.isfile(p)), None)
if not font_file:
    raise RuntimeError(f"No valid font found in {CONFIG['font_paths']}")
HDR_FONT = ImageFont.truetype(font_file, CONFIG["font_size_h"])
ROW_FONT = ImageFont.truetype(font_file, CONFIG["font_size"])

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

state_locks: dict[int, asyncio.Lock] = {}

def _get_state_file(ch: int) -> str:
    return f"state_{ch}.json"

async def save_state(ch: int) -> None:
    lock = state_locks.setdefault(ch, asyncio.Lock())
    async with lock:
        payload = {
            "ongoing_bans":    ongoing_bans[ch],
            "match_turns":     match_turns[ch],
            "match_times":     match_times[ch],
            "channel_teams":   list(channel_teams[ch]),
            "channel_messages": channel_messages.get(ch),
            "channel_flip":    channel_flip.get(ch),
            "channel_decision": channel_decision.get(ch),
            "channel_mode":    channel_mode.get(ch),
            "channel_host":    channel_host.get(ch),
        }
        tmp_path = _get_state_file(ch) + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, _get_state_file(ch))

async def load_state(ch: int) -> None:
    lock = state_locks.setdefault(ch, asyncio.Lock())
    async with lock:
        path = _get_state_file(ch)
        if not os.path.isfile(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except json.JSONDecodeError:
            return
        ongoing_bans[ch]       = data.get("ongoing_bans", {})
        match_turns[ch]        = data.get("match_turns")
        match_times[ch]        = data.get("match_times")
        channel_teams[ch]      = tuple(data.get("channel_teams", []))
        if data.get("channel_messages") is not None:
            channel_messages[ch] = data["channel_messages"]
        channel_flip[ch]       = data.get("channel_flip")
        channel_decision[ch]   = data.get("channel_decision")
        channel_mode[ch]       = data.get("channel_mode")
        channel_host[ch]       = data.get("channel_host")
        
# ─── Config Loaders & Helpers ──────────────────────────────────────────────────
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

def create_ban_image_bytes(
    maps, bans, mode, flip_winner, host_key, decision_choice,
    current_turn, match_time_iso=None, final=False
) -> BytesIO:
    # 1) Build your PIL Image exactly as before, but don’t save it to a file:
    img = create_ban_status_image(   # assume you refactor your existing function body into one that returns Image
        maps, bans, mode, flip_winner, host_key, decision_choice,
        current_turn, match_time_iso, final
    )

    # 2) Dump it into a BytesIO buffer
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

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
) -> Image:
    # — Load fonts with fallback —
    try:
        hdr_font = HDR_FONT 
        row_font = ROW_FONT
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
    img_h = header_h + (rows + 1) * row_h + padding

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
    
    # — Draw column headers row —
    header_row_y = header_h
    
    # Team A header (spanning first cell)
    draw.rectangle([grid_x0, header_row_y, grid_x0 + cell_w, header_row_y + row_h], fill="lightgray", outline="black")
    text = team_a_name or "Team A"
    bbox = measure.textbbox((0,0), text, font=row_font)
    w = bbox[2] - bbox[0]; h = bbox[3] - bbox[1]
    draw.text((grid_x0 + (cell_w - w)/2, header_row_y + (row_h - h)/2), text, font=row_font, fill="black")
    
    # Maps header
    mid_x = grid_x0 + cell_w
    draw.rectangle([mid_x, header_row_y, mid_x + cell_w, header_row_y + row_h], fill="lightgray", outline="black")
    text = "Maps"
    bbox = measure.textbbox((0,0), text, font=row_font)
    w = bbox[2] - bbox[0]; h = bbox[3] - bbox[1]
    draw.text((mid_x + (cell_w - w)/2, header_row_y + (row_h - h)/2), text, font=row_font, fill="black")
    
    # Team B header
    right_x = grid_x0 + 2 * cell_w
    draw.rectangle([right_x, header_row_y, right_x + cell_w, header_row_y + row_h], fill="lightgray", outline="black")
    text = team_b_name or "Team B"
    bbox = measure.textbbox((0,0), text, font=row_font)
    w = bbox[2] - bbox[0]; h = bbox[3] - bbox[1]
    draw.text((right_x + (cell_w - w)/2, header_row_y + (row_h - h)/2), text, font=row_font, fill="black")
    
    # Adjust grid start below header row
    grid_y0 = header_row_y + row_h
    half_w = cell_w // 2
    for i, m in enumerate(maps):
        name = m["name"]
        y0 = grid_y0 + i * row_h
        
        # Left team (Team A) Allied cell
        x0 = grid_x0
        x1 = x0 + half_w
        ta = bans[name]["team_a"]
        
        if "Allied" in ta["manual"]:
            color = "red"
        elif "Allied" in ta["auto"]:
            color = "orange"
        else:
            color = "white"
        
        draw.rectangle([x0, y0, x1, y0 + row_h], fill=color, outline="black")
        text = "Allies"
        bbox = measure.textbbox((0,0), text, font=row_font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text((x0 + (half_w - w)/2, y0 + (row_h - h)/2), text, font=row_font, fill="black")
        
        # Left team (Team A) Axis cell
        x0 = grid_x0 + half_w
        x1 = grid_x0 + cell_w
        
        if "Axis" in ta["manual"]:
            color = "red"
        elif "Axis" in ta["auto"]:
            color = "orange"
        else:
            color = "white"
        
        draw.rectangle([x0, y0, x1, y0 + row_h], fill=color, outline="black")
        text = "Axis"
        bbox = measure.textbbox((0,0), text, font=row_font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text((x0 + (half_w - w)/2, y0 + (row_h - h)/2), text, font=row_font, fill="black")
        
        # Center map name cell
        x0 = grid_x0 + cell_w
        x1 = x0 + cell_w
        draw.rectangle([x0, y0, x1, y0 + row_h], fill="white", outline="black")
        bbox = measure.textbbox((0,0), name, font=row_font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text((x0 + (cell_w - w)/2, y0 + (row_h - h)/2), name, font=row_font, fill="black")
        
        # Right team (Team B) Allied cell
        x0 = grid_x0 + 2 * cell_w
        x1 = x0 + half_w
        tb = bans[name]["team_b"]
        
        if "Allied" in tb["manual"]:
            color = "red"
        elif "Allied" in tb["auto"]:
            color = "orange"
        else:
            color = "white"
        
        draw.rectangle([x0, y0, x1, y0 + row_h], fill=color, outline="black")
        text = "Allies"
        bbox = measure.textbbox((0,0), text, font=row_font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text((x0 + (half_w - w)/2, y0 + (row_h - h)/2), text, font=row_font, fill="black")
        
        # Right team (Team B) Axis cell
        x0 = grid_x0 + 2 * cell_w + half_w
        x1 = x0 + half_w
        
        if "Axis" in tb["manual"]:
            color = "red"
        elif "Axis" in tb["auto"]:
            color = "orange"
        else:
            color = "white"

        draw.rectangle([x0, y0, x1, y0 + row_h], fill=color, outline="black")
        text = "Axis"
        bbox = measure.textbbox((0,0), text, font=row_font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text((x0 + (half_w - w)/2, y0 + (row_h - h)/2), text, font=row_font, fill="black")


    # — Return PIL Image —
    return img

# ─── Messaging Helper ─────────────────────────────────────────────────────────
async def update_status_message(
    channel_id: int,
    message_id: Optional[int],
    image_source: Union[str, BytesIO],
    embed: Optional[discord.Embed] = None
) -> None:
    channel = bot.get_channel(channel_id)
    
    # Prepare the discord.File object
    if isinstance(image_source, BytesIO):
        # In‐memory buffer → give it a filename
        file = discord.File(fp=image_source, filename=f"ban_status_{channel_id}.png")
    else:
        # Filesystem path
        file = discord.File(image_source, filename=os.path.basename(image_source))

    if message_id:
        try:
            msg = await channel.fetch_message(message_id)
            # Use files=[…], not attachments
            await msg.edit(files=[file], embed=embed)
        except Exception:
            # fallback: send a fresh message
            new = await channel.send(file=file, embed=embed)
            channel_messages[channel_id] = new.id
            await save_state(ch)
    else:
        new = await channel.send(file=file, embed=embed)
        channel_messages[channel_id] = new.id
        await save_state(channel)

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
    await save_state(ch)
        
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
    await save_state(ch)

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

@bot.tree.command(
    name="ban_map",
    description="Ban a map for a given side"
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
    channel = bot.get_channel(channel_id)
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
    
    # 2a) Prevent double-bans or invalid bans
    combos = remaining_combos(ch)
    # all sides still allowed for this map
    valid_sides = [ side for m, _, side in combos if m == map_name ]
    if not valid_sides:
        return await interaction.response.send_message(
            f"❌ `{map_name}` is not available for ban or already fully banned.",
            ephemeral=True
        )
    if side not in valid_sides:
        return await interaction.response.send_message(
            f"❌ `{side}` cannot ban `{map_name}` right now.",
            ephemeral=True
        )
    

    if final_combo:
        # --- FINAL BRANCH: lock in and send in one shot ---
        await interaction.response.defer()
        tb = ongoing_bans.setdefault(ch, {})
        tb.setdefault(map_name, {"team_a":{"manual":[],"auto":[]},"team_b":{"manual":[],"auto":[]}})
        tk = match_turns[ch]
        #tb[map_name][tk]["manual"].append(side)
        other = "team_b" if tk=="team_a" else "team_a"
        #tb[map_name][other]["auto"].append("Axis" if side=="Allied" else "Allied")
        #match_turns[ch] = other
        await save_state(channel)


        buf = create_ban_image_bytes(
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

        # 6) Build the status embed
        A = team_a_name; B = team_b_name
        coin_winner = A if channel_flip[ch]=="team_a" else B
        host_name  = channel_host[ch]
        mode       = channel_mode[ch]
        # Safely format match time, skipping placeholders
        match_time = match_times.get(ch)
        if match_time and match_time not in ("Undecided", "TBD"):
            try:
                dt = parser.isoparse(match_time).astimezone(pytz.timezone(CONFIG["user_timezone"]))
                time_str = dt.strftime("%Y-%m-%d %H:%M %Z")
            except Exception:
                time_str = "Undecided"
        else:
            time_str = "Undecided"
        current_key = match_turns.get(ch)
        current_name= A if current_key=="team_a" else B

        embed = discord.Embed(title="Match Status")
        embed.add_field(name="Team A: ",  value=team_a_name,  inline=True)
        embed.add_field(name="Team B: ",  value=team_b_name,  inline=True)
        embed.add_field(name="Flip Winner",   value=coin_winner,   inline=True)
        embed.add_field(name="Map Host",      value=host_name,     inline=True)
        embed.add_field(name="Mode",          value=mode,          inline=True)
        embed.add_field(name="Match Time",    value=time_str,      inline=True)
        embed.add_field(name="Final Ban",  value=current_name,  inline=True)
        embed.add_field(name="Stage", value="Map ban complete",  inline=False)
    
        await update_status_message(
            ch,
            channel_messages[ch],
            buf,
            embed=embed
        )
        
        # Then confirm privately
        msg = await interaction.followup.send("✅ Map ban confirmed.", ephemeral=True)
        asyncio.create_task(delete_later(msg, 5.0))
        
        # — Post a public winner prediction poll —
        channel = bot.get_channel(ch)
        poll = await channel.send(
            "**Winner Predictions**\n"
            "React below to predict the match winner:\n"
            "🇦 for **" + team_a_name + "**\n"
            "🇧 for **" + team_b_name + "**"
)
        await poll.add_reaction("🇦")
        await poll.add_reaction("🇧")
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
    await save_state(channel)

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
    
    # 6) Build the status embed
    A = team_a_name; B = team_b_name
    coin_winner = A if channel_flip[ch]=="team_a" else B
    host_name  = channel_host[ch]
    mode       = channel_mode[ch]
    # Safely format match time, skipping placeholders
    match_time = match_times.get(ch)
    if match_time and match_time not in ("Undecided", "TBD"):
        try:
            dt = parser.isoparse(match_time).astimezone(pytz.timezone(CONFIG["user_timezone"]))
            time_str = dt.strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            time_str = "Undecided"
    else:
        time_str = "Undecided"
    current_key = match_turns.get(ch)
    current_name= A if current_key=="team_a" else B

    embed = discord.Embed(title="Match Status")
    embed.add_field(name="Team A: ",  value=team_a_name,  inline=True)
    embed.add_field(name="Team B: ",  value=team_b_name,  inline=True)
    embed.add_field(name="Flip Winner",   value=coin_winner,   inline=True)
    embed.add_field(name="Map Host",      value=host_name,     inline=True)
    embed.add_field(name="Mode",          value=mode,          inline=True)
    embed.add_field(name="Match Time",    value=time_str,      inline=True)
    embed.add_field(name="Current Turn",  value=current_name,  inline=True)
    embed.add_field(name="Stage", value="Map ban ongoing",  inline=False)

    await update_status_message(
        ch,
        channel_messages[ch],
        buf,
        embed=embed
    )

    # Then confirm privately
    msg = await interaction.followup.send("✅ Updated.", ephemeral=True)
    asyncio.create_task(delete_later(msg, 5.0))
    return
      
@bot.tree.command(
    name="match_time",
    description="Set the scheduled match time"
)
@app_commands.describe(
    time="ISO-8601 datetime (with timezone) for the match -> ex. 2025-05-21T18:00:00-04:00"
)
async def match_time_cmd(
    interaction: discord.Interaction,
    time: str
) -> None:
    ch = interaction.channel_id
    channel = bot.get_channel(channel_id)
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
        await save_state(ch)
    except Exception as e:
        msg = await interaction.followup.send(
            f"❌ Invalid datetime: {e}", 
            ephemeral=True
        )
        asyncio.create_task(delete_later(msg, 5.0))
        return
        
    # 5) Rebuild the image (now with the new time included)
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

    # 6) Build the status embed
    A = team_a_name; B = team_b_name
    coin_winner = A if channel_flip[ch]=="team_a" else B
    host_name  = channel_host[ch]
    mode       = channel_mode[ch]
    # Safely format match time, skipping placeholders
    match_time = match_times.get(ch)
    if match_time and match_time not in ("Undecided", "TBD"):
        try:
            dt = parser.isoparse(match_time).astimezone(pytz.timezone(CONFIG["user_timezone"]))
            time_str = dt.strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            time_str = "Undecided"
    else:
        time_str = "Undecided"
    current_key = match_turns.get(ch)
    current_name= A if current_key=="team_a" else B

    embed = discord.Embed(title="Match Status")
    embed.add_field(name="Team A: ",  value=team_a_name,  inline=True)
    embed.add_field(name="Team B: ",  value=team_b_name,  inline=True)
    embed.add_field(name="Flip Winner",   value=coin_winner,   inline=True)
    embed.add_field(name="Map Host",      value=host_name,     inline=True)
    embed.add_field(name="Mode",          value=mode,          inline=True)
    embed.add_field(name="Match Time",    value=time_str,      inline=True)
    embed.add_field(name="Final Ban",  value=current_name,  inline=True)
    embed.add_field(name="Stage", value="Map ban complete, time updated",  inline=False)


    # 7) Edit the original image message with both image + embed
    await update_status_message(
        ch,
        channel_messages[ch],
        buf,
        embed=embed
    )

    # Then confirm privately
    msg = await interaction.followup.send("✅ Updated.", ephemeral=True)
    asyncio.create_task(delete_later(msg, 5.0))
    return
    
@bot.tree.command(
    name="match_decide",
    description="Choose whether the flip-winner bans first or hosts first if no Middle Ground Rule"
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

    await save_state(ch)

    # 6) Rebuild the updated status image
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

    # 7) Build the status embed
    A = team_a_name; B = team_b_name
    coin_winner = A if channel_flip[ch]=="team_a" else B
    host_name  = channel_host[ch]
    mode       = channel_mode[ch]
    # Safely format match time, skipping placeholders
    match_time = match_times.get(ch)
    if match_time and match_time not in ("Undecided", "TBD"):
        try:
            dt = parser.isoparse(match_time).astimezone(pytz.timezone(CONFIG["user_timezone"]))
            time_str = dt.strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            time_str = "Undecided"
    else:
        time_str = "Undecided"
    current_key = match_turns.get(ch)
    current_name= A if current_key=="team_a" else B

    embed = discord.Embed(title="Match Status")
    embed.add_field(name="Team A: ",  value=team_a_name,  inline=True)
    embed.add_field(name="Team B: ",  value=team_b_name,  inline=True)
    embed.add_field(name="Flip Winner",   value=coin_winner,   inline=True)
    embed.add_field(name="Map Host",      value=host_name,     inline=True)
    embed.add_field(name="Mode",          value=mode,          inline=True)
    embed.add_field(name="Match Time",    value=time_str,      inline=True)
    embed.add_field(name="Current Turn",  value=current_name,  inline=True)
    embed.add_field(name="Stage", value="Starting",  inline=False)


    # 8) Edit the original image message with both image + embed
    await update_status_message(
        ch,
        channel_messages[ch],
        buf,
        embed=embed
    )

    # Then confirm privately
    msg = await interaction.followup.send("✅ Updated.", ephemeral=True)
    asyncio.create_task(delete_later(msg, 5.0))
    return

@bot.tree.command(
    name="match_delete",
    description="End and remove the current match"
)
async def match_delete(interaction: discord.Interaction) -> None:
    ch = interaction.channel_id
    channel = bot.get_channel(channel_id)
    
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
    await save_state(channel)

    # 6) Confirm deletion to the user
    msg = await interaction.followup.send(
        "✅ Match has been deleted and state cleared.", 
        ephemeral=True
    )
    asyncio.create_task(delete_later(msg, 5.0))
    return

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
    await bot.tree.sync()
    print("Bot is ready.")    
    for path in glob.glob("state_*.json"):
        ch = int(os.path.basename(path).split("_")[1].split(".")[0])
        await load_state(ch)

bot.run(os.getenv("DISCORD_TOKEN"))