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
import textwrap
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
    "row_font_size":    168,
    "header_font_size": 240,
    "pad_x_factor":     0.5,
    "pad_y_factor":     0.25,
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
final: Optional[bool] = False

going  = {}
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
        data = json.load(open(STATE_FILE))
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
    channel_host.update({int(k):tuple(v) for k,v in data.get("channel_host",{}).items()})


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
        "channel_host":    {str(k):list(v) for k,v in channel_host.items()},
    }
    with open(STATE_FILE, "w") as f:
        json.dump(payload, f, indent=2)

# ─── Config Loaders & Helpers ──────────────────────────────────────────────────
def load_teammap() -> dict:
    return json.load(open(CONFIG["teammap_file"]))

def load_maplist() -> List[dict]:
    return json.load(open(CONFIG["maplist_file"]))["maps"]

def determine_ban_option(a: str, b: str, cfg: dict) -> str:
    return cfg.get("region_pairings", {}).get(a, {}).get(b, "ExtraBan")

def build_banners(
    mode: str,
    flip_winner: Optional[str],
    decision: Optional[str],
    current: Optional[str],
    match_time_iso: Optional[str],
    final: bool
) -> Tuple[str, str]:
    global team_a_name, team_b_name

    team_a = team_a_name or "Team A"
    team_b = team_b_name or "Team B"

    if final:
        banner1 = "Final Map Locked"
    elif mode == "ExtraBan":
        banner1 = f"Extra Ban Winner: {team_a if flip_winner=='team_a' else team_b}"
    else:
        banner1 = f"Flip Winner: {team_a if flip_winner=='team_a' else team_b}"

    if decision == "ban":
        banner2 = f"Ban Turn: {team_a if current=='team_a' else team_b}"
    elif decision == "host":
        banner2 = f"Host Turn: {team_a if current=='team_a' else team_b}"
    else:
        banner2 = f"Current Turn: {team_a if current=='team_a' else team_b}"

    if match_time_iso:
        try:
            dt = parser.isoparse(match_time_iso)
            user_tz = pytz.timezone(CONFIG["user_timezone"])
            local_dt = dt.astimezone(user_tz)
            banner2 += "   |   " + local_dt.strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            pass

    return banner1, banner2
    
def remaining_combos(ch: int) -> List[Tuple[str,str,str]]:
    combos = []
    for m, tb in ongoing_bans.get(ch, {}).items():
        for team_key in ("team_a", "team_b"):
            for side in ("Allied", "Axis"):
                if side not in tb[team_key]["manual"] and side not in tb[team_key]["auto"]:
                    combos.append((m, team_key, side))
    return combos

def is_ban_complete(ch: int) -> bool:
    return len(remaining_combos) == 2 and combos[0][0] == combos[1][0]

async def respond_and_edit(interaction, img_path: str):
    """Sends the initial message and saves message_id."""
    await interaction.response.send_message(file=discord.File(img_path))
    msg = await interaction.original_response()
    return msg.id

async def defer_and_followup(interaction, img_path: str, confirm: str = None):
    """Defers, edits the stored message, and optionally sends a confirmation."""
    await interaction.response.defer()
    await update_status_message(interaction.channel_id, None, img_path)
    if confirm:
        await interaction.followup.send(confirm, ephemeral=True)
        
def create_ban_status_image(
    maps: List[dict],
    bans: Dict[str, Dict[str, List[str]]],
    mode: str,
    flip_winner: Optional[str],
    decision: Optional[str],
    current: Optional[str],
    match_time_iso: Optional[str] = None,
    final: bool = False
) -> str:
    """Generate a 3-column banner+grid image matching your example."""
    # — Fonts & fallback —
    try:
        hdr_font = ImageFont.truetype(CONFIG["font_paths"][0], CONFIG["header_font_size"])
        row_font = ImageFont.truetype(CONFIG["font_paths"][0], CONFIG["row_font_size"])
    except OSError:
        hdr_font = ImageFont.load_default()
        row_font = ImageFont.load_default()

    # — Build the two header lines —
    # (You can replace with your build_banners helper if you like.)
    tA, tB = team_a_name or "Team A", team_b_name or "Team B"
    line1 = f"{tA}    Maps    {tB}"
    if match_time_iso:
        dt = parser.isoparse(match_time_iso).astimezone(pytz.timezone(CONFIG["user_timezone"]))
        time_str = dt.strftime("%Y-%m-%d %H:%M %Z")
        line0 = f"{line1}    |    Time: {time_str}"
    else:
        line0 = line1

    # — Measure text via a temp draw —
    tmp = Image.new("RGB", (1,1))
    meas = ImageDraw.Draw(tmp)
    x0,y0,x1,y1 = meas.textbbox((0,0), line0, font=hdr_font)
    header_h = (y1-y0) * 2 + 20  # two lines + padding

    # — Grid dimensions —
    n = len(maps)
    col_w = 200
    map_w = 300
    total_w = col_w + map_w + col_w
    row_h = CONFIG["row_font_size"] + 10

    total_h = header_h + n * row_h

    # — New canvas & real draw —
    img = Image.new("RGBA", (total_w, total_h), "white")
    draw = ImageDraw.Draw(img)

    # — Draw headers —
    draw.text((10,10), line0, font=hdr_font, fill="black")
    draw.text((10,10 + (y1-y0) + 5), line0, font=hdr_font, fill="black")  # duplicate if you want two lines

    # — Sub-column headers under each team —
    sub_y = header_h - row_h
    # Team A sub-headers
    draw.text((10, sub_y),        "Allied", font=row_font, fill="black")
    draw.text((10+col_w//2,sub_y),"Axis",   font=row_font, fill="black")
    # Team B sub-headers
    base = col_w + map_w
    draw.text((base+10, sub_y),        "Allied", font=row_font, fill="black")
    draw.text((base+10+col_w//2, sub_y),"Axis",   font=row_font, fill="black")

    # — Draw each map row —
    for i, m in enumerate(maps):
        y = header_h + i*row_h
        # Center map name
        mx = col_w + (map_w//2)
        draw.text((mx - len(m["name"])*4, y), m["name"], font=row_font, fill="black")

        tb = bans.get(m["name"], {"team_a":{"manual":[],"auto":[]},"team_b":{"manual":[],"auto":[]}})
        for ti, team_key in enumerate(("team_a","team_b")):
            x_base = ti*(col_w+map_w)
            # determine which side is banned
            man = tb[team_key]["manual"]
            auto= tb[team_key]["auto"]
            for si, side in enumerate(("Allied","Axis")):
                x = x_base + (col_w//2)*si + 5
                # color
                if final and len(bans)==1 and side in man:
                    color="green"
                elif side in man or side in auto:
                    color="red"
                else:
                    color="yellow"
                draw.rectangle([x-2, y-2, x + (col_w//2)-10, y+row_h-2], fill=color)
                draw.text((x, y), side, font=row_font, fill="black")

    # — Save & return path —
    out = os.path.join(os.getcwd(), CONFIG["output_image"])
    img.save(out, optimize=True, compress_level=9)
    return out

# ─── Messaging Helper ─────────────────────────────────────────────────────────
async def update_status_message(
    channel_id: int,
    message_id: Optional[int],
    image_path: str,
    embed: Optional[discord.Embed] = None
) -> None:
    """
    Edits the existing match‐status message (if message_id is set)
    to replace its attachment with the new image and update its embed.
    """
    channel = bot.get_channel(channel_id)
    if message_id:
        try:
            msg = await channel.fetch_message(message_id)
            file = discord.File(image_path, filename=os.path.basename(image_path))
            kwargs = {"attachments": [file]}
            if embed:
                kwargs["embed"] = embed
            await msg.edit(**kwargs)
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
        ongoing_bans, match_turns, channel_teams,
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
    mode="ExtraBan or Standard",
    description="Optional match description"
)
async def match_create(
    interaction: discord.Interaction,
    team_a:      discord.Role,
    team_b:      discord.Role,
    mode:        Literal["ExtraBan", "Standard"],
    description: Optional[str] = None
) -> None:
    # 1) Set global display names
    global team_a_name, team_b_name
    team_a_name, team_b_name = team_a.name, team_b.name

    # 2) Initialize in‐memory state
    load_state()
    ch = interaction.channel_id
    channel_teams[ch]      = (team_a.name, team_b.name)
    channel_mode[ch]       = mode
    flip_key               = random.choice(("team_a", "team_b"))
    channel_flip[ch]       = flip_key
    match_turns[ch]        = flip_key if mode == "ExtraBan" else "team_a"
    ongoing_bans[ch]       = {
        m["name"]: {
            "team_a": {"manual": [], "auto": []},
            "team_b": {"manual": [], "auto": []}
        }
        for m in load_maplist()
    }
    save_state()

    # 3) Generate the initial status image
    img = create_ban_status_image(
        load_maplist(),
        ongoing_bans[ch],
        channel_mode[ch],
        channel_flip[ch],
        channel_decision.get(ch),
        match_turns[ch],
        match_time_iso=match_times.get(ch),
        final=False
    )

    # 4) Send & cache the message ID
    msg_id = await respond_and_edit(interaction, img)
    channel_messages[ch] = msg_id
    save_state()
    
    # 1) Build the status embed
    A = team_a_name; B = team_b_name
    coin_winner = A if channel_flip[ch]=="team_a" else B
    host_key   = channel_host.get(ch)
    host_name  = A if host_key=="team_a" else B
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

    # 2) Edit the original image message with both image + embed
    await interaction.response.defer()
    await update_status_message(ch, None, img, embed)

    # 3) Confirm
    await interaction.followup.send("✅ Match Created.", ephemeral=True)
    

@bot.tree.command(
    name="ban_map",
    description="Ban a map for a given side",
    guild=discord.Object(id=1366830976369557654)
)
@app_commands.describe(map_name="Map to ban", side="Allied or Axis")
@app_commands.autocomplete(map_name=map_autocomplete, side=side_autocomplete)
async def ban_map(
    interaction: discord.Interaction,
    map_name: str,
    side: str
) -> None:
    ch = interaction.channel_id
    
    # 1) Check turn order
    current = match_turns.get(ch)
    if current is None:
        return await interaction.response.send_message(
            "❌ No active match in this channel.", ephemeral=True
        )
    expected_role = channel_teams[ch][0] if current=="team_a" else channel_teams[ch][1]
    if expected_role not in [r.name for r in interaction.user.roles]:
        return await interaction.response.send_message(
            f"❌ Not your turn: waiting on **{expected_role}** to ban.", ephemeral=True
        )
        
    # 2) Check for final two-combo lock and finalize early
    combos = remaining_combos(ch)
    if len(combos)==2 and combos[0][0]==combos[1][0]:
        # Final ban locking
        img = create_ban_status_image(
            load_maplist(),
            ongoing_bans[ch],
            channel_mode[ch],
            channel_flip[ch],
            channel_decision.get(ch),
            match_turns[ch],
            match_time_iso=match_times.get(ch),
            final=True
        )
        # Acknowledge and edit
        await interaction.response.defer()
        await update_status_message(ch, None, img)
        return await interaction.followup.send(
            "✅ Ban phase complete — final map locked.", ephemeral=True
        )
        
    # 3) Normal ban path
    await interaction.response.defer()

    # Record the manual ban
    tb = ongoing_bans.setdefault(ch, {})
    tb.setdefault(map_name, {"team_a":{"manual":[],"auto":[]},"team_b":{"manual":[],"auto":[]}})
    tk = "team_a" if current=="team_a" else "team_b"
    tb[map_name][tk]["manual"].append(side)

    # Auto-ban opposite side for the other team
    other = "team_b" if tk=="team_a" else "team_a"
    opposite = "Axis" if side=="Allied" else "Allied"
    tb[map_name][other]["auto"].append(opposite)

    # Advance turn
    match_turns[ch] = other

    # Persist state
    save_state()

    # Rebuild image
    img = create_ban_status_image(
        load_maplist(),
        ongoing_bans[ch],
        channel_mode[ch],
        channel_flip[ch],
        channel_decision.get(ch),
        match_turns[ch],
        match_time_iso=match_times.get(ch),
        final=False
    )

    # Edit original message and confirm
    await update_status_message(ch, None, img)
    await interaction.followup.send("✅ Ban recorded.", ephemeral=True)
    
    # 1) Build the status embed
    A = team_a_name; B = team_b_name
    coin_winner = A if channel_flip[ch]=="team_a" else B
    host_key   = channel_host.get(ch)
    host_name  = A if host_key=="team_a" else B
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

    # 2) Edit the original image message with both image + embed
    await interaction.response.defer()
    await update_status_message(ch, None, img, embed)

    # 3) Confirm
    await interaction.followup.send("✅ Ban recorded.", ephemeral=True)
      
@bot.tree.command(
    name="match_time",
    description="Set the scheduled match time",
    guild=discord.Object(id=1366830976369557654)
)
@app_commands.describe(
    time="ISO-8601 datetime (with timezone) for the match"
)
async def match_time_cmd(
    interaction: discord.Interaction,
    time: str
) -> None:
    ch = interaction.channel_id

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
        load_maplist(),
        ongoing_bans[ch],
        channel_mode[ch],
        channel_flip[ch],
        channel_decision.get(ch),
        match_turns[ch],
        match_time_iso=match_times[ch],
        final=False
    )

    # 6) Edit the original match image
    await update_status_message(ch, None, img)

    # 7) Confirm to the user
    await interaction.followup.send(
        "✅ Match time updated on the image.", 
        ephemeral=True
    )
    
    # 1) Build the status embed
    A = team_a_name; B = team_b_name
    coin_winner = A if channel_flip[ch]=="team_a" else B
    host_key   = channel_host.get(ch)
    host_name  = A if host_key=="team_a" else B
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

    # 2) Edit the original image message with both image + embed
    await interaction.response.defer()
    await update_status_message(ch, None, img, embed)

    # 3) Confirm
    await interaction.followup.send("✅ Ban recorded.", ephemeral=True)
@bot.tree.command(
    name="match_decide",
    description="Choose whether the flip-winner bans first or hosts first",
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
        load_maplist(),
        ongoing_bans[ch],
        channel_mode[ch],
        channel_flip[ch],
        channel_decision.get(ch),
        match_turns[ch],
        match_time_iso=match_times.get(ch),
        final=False
    )

    # 7) Edit the original match message
    await update_status_message(ch, None, img)

    # 8) Confirm to the user
    await interaction.followup.send(
        "✅ Decision recorded; turn order updated.", 
        ephemeral=True
    )
    
    # 1) Build the status embed
    A = team_a_name; B = team_b_name
    coin_winner = A if channel_flip[ch]=="team_a" else B
    host_key   = channel_host.get(ch)
    host_name  = A if host_key=="team_a" else B
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

    # 2) Edit the original image message with both image + embed
    await interaction.response.defer()
    await update_status_message(ch, None, img, embed)

    # 3) Confirm
    await interaction.followup.send("✅ Decision recorded.", ephemeral=True)


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
    team_roles = channel_teams.get(ch, ())
    if not any(r.name in team_roles for r in interaction.user.roles):
        return await interaction.response.send_message(
            "❌ Only participants of this match may delete it.", ephemeral=True
        )

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
        channel_mode
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