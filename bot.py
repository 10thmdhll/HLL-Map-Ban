import os
import json
import random
import asyncio
from typing import List, Tuple, Optional, Literal

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

def is_ban_complete(ch: int) -> bool:
    combos = [
        (m, t, s)
        for m, tb in ongoing_bans.get(ch, {}).items()
        for t in ("team_a", "team_b")
        for s in ("Allied", "Axis")
        if s not in tb[t]["manual"] and s not in tb[t]["auto"]
    ]
    return len(combos) == 2 and combos[0][0] == combos[1][0]

def create_ban_status_image(
    maps: List[dict],
    bans: dict[str, dict[str, List[str]]],
    # these args can stay for signature compatibility, but will be ignored:
    _team_a: str,
    _team_b: str,
    mode: str, flip_winner: Optional[str],
    decision_choice: Optional[str],
    current_turn: Optional[str],
    match_time_iso: Optional[str] = None,
    final: bool = False,
    channel_host: str = ""
) -> str:
    global team_a_name, team_b_name
    # Force-override any passed‐in team names with the globals
    team_a = team_a_name or "Team A"
    team_b = team_b_name or "Team B"
    """Generates ban status image, highlighting final remaining combo if final=True."""
    from PIL import Image
    row_fs, hdr_fs = CONFIG["row_font_size"], CONFIG["header_font_size"]
    pad_x = int(hdr_fs * CONFIG["pad_x_factor"])
    pad_y = int(hdr_fs * CONFIG["pad_y_factor"])
    max_w = CONFIG["max_inline_width"]
    qc, cl, opt = (
        CONFIG["quantize_colors"],
        CONFIG["compress_level"],
        CONFIG["optimize_png"]
    )
    out_path = CONFIG["output_image"]

    # load fonts
    row_font = hdr_font = None
    for fp in CONFIG["font_paths"]:
        try:
            row_font = ImageFont.truetype(fp, row_fs)
            hdr_font = ImageFont.truetype(fp, hdr_fs)
            break
        except:
            continue
    if not row_font:
        row_font = hdr_font = ImageFont.load_default()

    def measure(txt: str, fnt) -> Tuple[int,int]:
        b = fnt.getbbox(txt)
        return b[2]-b[0], b[3]-b[1]

    # determine final combo if needed
    final_map = final_side1 = final_side2 = None
    if final and current_turn is None:
        # use is_ban_complete logic to find remaining map and sides
        combos = [
            (m, t, s)
            for m, tb in bans.items()
            for t in ("team_a","team_b")
            for s in ("Allied","Axis")
            if s not in tb[t]["manual"] and s not in tb[t]["auto"]
        ]
        if len(combos)==2 and combos[0][0]==combos[1][0]:
            final_map = combos[0][0]
            final_side1 = combos[0][2]  # side for team from combos order
            final_side2 = combos[1][2]

    # build banner lines, adjust if final
    if final and final_map:
        banner1 = f"{team_a} = {final_side1}   |   {team_b} = {final_side2}"
        banner2 = "Match Time: {match_time_iso}  |  Final choice locked."  
    else:
        fw = flip_winner
        if mode == "ExtraBan":
            first_lbl, host_field = fw, "Middle ground rules in effect."
        else:
            if decision_choice is None:
                first_lbl, host_field = "TBD", f"{fw} chooses host"
            elif decision_choice == "Ban":
                first_lbl = fw
                other = team_b if fw==team_a else team_a
                host_field = f"Host: {other}"
            else:
                other = team_b if fw==team_a else team_a
                first_lbl = other
                host_field = f"Host: {fw}"
        banner1 = f"Flip Winner: {fw}   |   First Ban: {first_lbl}   |   {host_field}"
        banner2 = f"Match Time: {match_time_iso}  |  Current Turn: {current_turn or 'TBD'}"
    
    # Show the team name instead of key
    current_team_name = team_a if current_turn == "team_a" else team_b if current_turn == "team_b" else "TBD"
    banner2 = f"Match Time: {match_time_iso}  |  Current Turn: {current_team_name}"
    
    side_sz = [measure(s, row_font) for s in ("Allied","Axis")]
    max_sw, max_sh = max(w for w,h in side_sz), max(h for w,h in side_sz)
    map_sz = [measure(m["name"], row_font) for m in maps] + [measure("Maps", hdr_font)]
    max_mw, max_mh = max(w for w,h in map_sz), max(h for w,h in map_sz)

    fw = flip_winner or "TBD"
    if mode == "ExtraBan":
        first_lbl, host_field = fw, "Middle ground rules in effect."
    else:
        if decision_choice is None:
            first_lbl, host_field = "TBD", f"{fw} chooses host"
        elif decision_choice == "ban":
            first_lbl = fw
            other     = team_b if fw==team_a else team_a
            host_field = f"Host: {other}"
        else:
            other     = team_b if fw==team_a else team_a
            first_lbl = other
            host_field = f"Host: {fw}"

    line1 = f"Flip Winner: {fw}   |   First Ban: {first_lbl}   |   {host_field}"
    line2 = f"Match Time: {match_time_iso}  |  Current Turn: {current_turn or 'TBD'}"
    b1w, b1h = measure(line1, hdr_font)
    b2w, b2h = measure(line2, hdr_font)

    base_sw = max(max_sw, measure("Allied",hdr_font)[0]) + pad_x*2
    ta_w, _ = measure(team_a, hdr_font)
    tb_w, _ = measure(team_b, hdr_font)
    req2 = max(2*base_sw, max(ta_w, tb_w) + pad_x*2)
    side_w = (req2 + 1)//2
    map_w  = max(max_mw, measure("Maps",hdr_font)[0]) + pad_x*2

    row_h = max(max_sh, max_mh) + pad_y*2
    h1, h2 = hdr_fs + pad_y, hdr_fs + pad_y
    banner_h = (b1h + pad_y*2) + (b2h + pad_y*2)

    total_w = max(side_w*4 + map_w, b1w + pad_x*2, b2w + pad_x*2)
    map_w   = total_w - side_w*4
    height  = banner_h + h1 + h2 + len(maps)*row_h + pad_y

    img  = Image.new("RGB", (total_w, height), (240,240,240))
    draw = ImageDraw.Draw(img)
    y = 0

    # Banner
    draw.rectangle([0,y,total_w,y+banner_h], fill=(220,220,255), outline="black")
    draw.text((total_w//2, y+(b1h+pad_y*2)//2), line1, font=hdr_font, anchor="mm", fill="black")
    draw.text((total_w//2, y+(b1h+pad_y*2)+(b2h+pad_y*2)//2), line2, font=hdr_font, anchor="mm", fill="black")
    y += banner_h

    # Headers
    draw.rectangle([0,y,2*side_w,y+h1], fill=(200,200,200), outline="black")
    draw.text((side_w,y+h1//2), team_a, font=hdr_font, anchor="mm", fill="black")
    draw.rectangle([2*side_w,y,2*side_w+map_w,y+h1], fill=(200,200,200), outline="black")
    draw.text((2*side_w+map_w//2,y+h1//2),"Maps", font=hdr_font, anchor="mm", fill="black")
    draw.rectangle([2*side_w+map_w,y,total_w,y+h1], fill=(200,200,200), outline="black")
    draw.text((2*side_w+map_w+side_w,y+h1//2), team_b, font=hdr_font, anchor="mm", fill="black")
    y += h1

    # Sub-headers
    labels = ["Allied","Axis","","Allied","Axis"]
    widths = [side_w, side_w, map_w, side_w, side_w]
    x = 0
    for w, lab in zip(widths, labels):
        draw.rectangle([x,y,x+w,y+h2], fill=(220,220,220), outline="black")
        if lab:
            draw.text((x+w//2,y+h2//2), lab, font=hdr_font, anchor="mm", fill="black")
        x += w
    y += h2

    # Map rows
    for m in maps:
        tbans = bans[m["name"]]
        x = 0
        for side in ("Allied","Axis"):
            c = (255,0,0) if side in tbans["team_a"]["manual"] \
                else (255,165,0) if side in tbans["team_a"]["auto"] \
                else (255,255,255)
            draw.rectangle([x,y,x+side_w,y+row_h], fill=c, outline="black")
            draw.text((x+side_w//2,y+row_h//2), side, font=row_font, anchor="mm", fill="black")
            x += side_w
        draw.rectangle([x,y,x+map_w,y+row_h], fill=(240,240,240), outline="black")
        draw.text((x+map_w//2,y+row_h//2), m["name"], font=row_font, anchor="mm", fill="black")
        x += map_w
        for side in ("Allied","Axis"):
            c = (255,0,0) if side in tbans["team_b"]["manual"] \
                else (255,165,0) if side in tbans["team_b"]["auto"] \
                else (255,255,255)
            draw.rectangle([x,y,x+side_w,y+row_h], fill=c, outline="black")
            draw.text((x+side_w//2,y+row_h//2), side, font=row_font, anchor="mm", fill="black")
            x += side_w
        y += row_h

    # Downscale for inline fit
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), resample=Image.Resampling.LANCZOS)

    # Quantize & save
    img = img.quantize(colors=qc, method=Image.FASTOCTREE)
    img.save(out_path, optimize=opt, compress_level=cl)
    return CONFIG["output_image"]

# ─── Messaging Helper ─────────────────────────────────────────────────────────
async def update_status_message(ch: int, content: Optional[str], img: str) -> None:
    channel = bot.get_channel(ch)
    if not channel:
        return
    file = discord.File(img)
    msg_id = channel_messages.get(ch)
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(content=content, attachments=[file])
            return
        except discord.NotFound:
            pass
    msg = await channel.send(content=content, file=file)
    channel_messages[ch] = msg.id
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
    return choices[:25]

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
    return choices[:25]

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
        
# ─── Slash Commands ─────────────────────────────────────────────────────────────
@bot.tree.command(
    name="match_create",
    description="Create a new match"
)
@app_commands.describe(
    team_a="Role for Team A",
    team_b="Role for Team B",
    title="Match title",
    description="Match description"
)
async def match_create(
    interaction: discord.Interaction,
    team_a: discord.Role,
    team_b: discord.Role,
    title: str,
    description: str = "No description provided"
) -> None:
    global team_a_name, team_b_name
    # Set global team names
    team_a_name = team_a.name
    team_b_name = team_b.name

    ch = interaction.channel_id
    if ch in ongoing_bans:
        await interaction.response.send_message("❌ Match already active.", ephemeral=True)
    
    cfg = load_teammap()
    maps = load_maplist()
    ra = cfg.get("team_regions", {}).get(team_a_name, "Unknown")
    rb = cfg.get("team_regions", {}).get(team_b_name, "Unknown")
    mode = determine_ban_option(ra, rb, cfg)

    # Coin flip
    winner_key = random.choice(["team_a", "team_b"])
    
    # Channel Host
    host_name = "Middle ground rules apply"
    channel_host[ch] = host_name
    
    # Initialize state
    channel_teams[ch] = (team_a_name, team_b_name)
    channel_mode[ch] = mode
    channel_flip[ch] = winner_key
    channel_decision[ch] = None
    match_turns[ch] = winner_key
    match_times[ch] = None
    channel_host[ch] = host_name
    ongoing_bans[ch] = {
        m["name"]: {"team_a": {"manual": [], "auto": []}, "team_b": {"manual": [], "auto": []}}
        for m in maps
    }
    save_state()

    # Send initial status image
    turn_name = ""
    final = False
    if match_turns[ch] == "team_a":
        turn_name = team_a_name
    if match_turns[ch] == "team_b":
        turn_name = team_b_name
    if final == True:
        turn_name = "Final"
        
    flip_name = ""
    if channel_flip[ch] == "team_a":
        flip_name = team_a_name
    if channel_flip[ch] == "team_b":
        flip_name = team_b_name

    # Send initial status image via update_status_message to enable future edits
    img = create_ban_status_image(
        load_maplist(), ongoing_bans[ch], team_a_name, team_b_name,
        channel_mode[ch], flip_name, channel_decision[ch], turn_name, None, False, host_name
    )
    # Post and store the message for later edits
    await update_status_message(ch, f"🎲 Match created: {team_a_name} vs {team_b_name}", img)
    save_state()
    
    await interaction.response.send_message("✅ Match is ready.", ephemeral=False)

@bot.tree.command(
    name="ban_map",
    description="Ban a map for a given side"
)
@app_commands.describe(map_name="Map to ban", side="Allied or Axis")
@app_commands.autocomplete(map_name=map_autocomplete, side=side_autocomplete)
async def ban_map(
    interaction: discord.Interaction,
    map_name: str,
    side: str
) -> None:
    ch = interaction.channel_id
    
    # Determine remaining ban options
    final = False
    remaining = [
        (m, t, s)
        for m, tb in ongoing_bans.get(ch, {}).items()
        for t in ("team_a", "team_b")
        for s in ("Allied", "Axis")
        if s not in tb[t]["manual"] and s not in tb[t]["auto"]
    ]
    # Only the current team may ban
    current_key = match_turns.get(ch)
    if not current_key:
        await interaction.response.send_message("❌ No match in progress.", ephemeral=True)
    expected_role = channel_teams[ch][0] if current_key=="team_a" else channel_teams[ch][1]
    if expected_role not in {r.name for r in interaction.user.roles}:
        await interaction.response.send_message("❌ Not your turn to ban.", ephemeral=True)
      
    # Persist if now final
    remaining_after = [
        (m, t, s)
        for m, tb2 in ongoing_bans[ch].items()
        for t in ("team_a","team_b")
        for s in ("Allied","Axis")
        if s not in tb2[t]["manual"] and s not in tb2[t]["auto"]
    ]    
    # Ban result image creation  
    turn_name = ""
    if match_turns[ch] == "team_a":
        turn_name = team_a_name
    if match_turns[ch] == "team_b":
        turn_name = team_b_name
    if final == True:
        turn_name = "Final"
    
    flip_name = ""
    if channel_flip[ch]=="team_a":
        flip_name = team_a_name
    if channel_flip[ch]=="team_b":
        flip_name = team_b_name
        
    host_name = "Middle ground rules apply"
    if channel_host[ch] == "team_a":
        host_name = team_a_name
    if channel_host[ch] == "team_b":
        host_name = team_b_name
         
    img = create_ban_status_image(
        load_maplist(),
        ongoing_bans[ch],
        team_a_name,
        team_b_name,
        channel_mode[ch],
        flip_name,
        channel_decision[ch],
        turn_name,
        match_times[ch],
        final,
        host_name
    )
    
    if len(remaining_after) >= 4:
        # Proceed with normal ban
        await interaction.response.defer()
        tb = ongoing_bans[ch].get(map_name)
        if tb is None:
            return await interaction.response.send_message("❌ Invalid map.", ephemeral=True)
        tk = current_key
        tb[tk]["manual"].append(side)
    
        # auto-ban opposing side
        other = "team_b" if tk=="team_a" else "team_a"
        tb[other]["auto"].append("Axis" if side=="Allied" else "Allied")
        match_turns[ch] = other
        
        host_name = "Middle ground rules apply"
        if channel_host[ch] == "team_a":
            host_name = team_a_name
        if channel_host[ch] == "team_b":
            host_name = team_b_name
        
        img = create_ban_status_image(
            load_maplist(),
            ongoing_bans[ch],
            team_a_name,
            team_b_name,
            channel_mode[ch],
            flip_name,
            channel_decision[ch],
            turn_name,
            match_times[ch],
            final,
            host_name
        )
        
        await update_status_message(ch, None, img)
        msg = await interaction.followup.send("✅ Ban recorded.", ephemeral=False)
        asyncio.create_task(delete_later(msg, 10)) 
    
    if len(remaining_after) <= 3:
        final = True
        await update_status_message(ch, None, img)
        await interaction.response.send_message("✅ Ban phase complete.", ephemeral=False)
        save_state()
      
@bot.tree.command(
    name="match_time",
    description="Set match date/time"
)
@app_commands.describe(time="ISO8601 datetime with timezone ex. 2025-05-21T18:00:00-04:00")
async def match_time(
    interaction: discord.Interaction,
    time: str
) -> None:
    ch = interaction.channel_id
    # Only team members may set match time
    team_a, team_b = channel_teams.get(ch, (None, None))
    user_roles = {r.name for r in interaction.user.roles}
    if team_a not in user_roles and team_b not in user_roles:
        return await interaction.response.send_message("❌ You’re not on a team for this match.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    ch = interaction.channel_id

    try:
        dt = parser.isoparse(time).astimezone(pytz.timezone(CONFIG["user_timezone"]))
        match_times[ch] = dt.isoformat()
        save_state()
    except Exception as e:
        return await interaction.followup.send(f"❌ Invalid datetime: {e}", ephemeral=True)
    
    display_time = dt.strftime("%Y-%m-%d %H:%M %Z")
    embed = discord.Embed(title="Match Scheduled")
    embed.add_field(name="Match Time", value=display_time, inline=False)
    await interaction.followup.send(embed=embed)
    
    final = False
    
    turn_name = ""
    if match_turns[ch] == "team_a":
        turn_name = team_a_name
    if match_turns[ch] == "team_b":
        turn_name = team_b_name
    if final == True:
        turn_name = "Final"
    
    flip_name = ""
    if channel_flip[ch]=="team_a":
        flip_name = team_a_name
    if channel_flip[ch]=="team_b":
        flip_name = team_b_name
        
    host_name = ""
    if channel_host[ch] == "team_a":
        host_name = team_a_name
    else:
        host_name = team_b_name
    
    img = create_ban_status_image(
        load_maplist(),
        ongoing_bans[ch],
        team_a_name,
        team_b_name,
        channel_mode[ch],
        flip_name,
        channel_decision[ch],
        turn_name,
        display_time,
        final,
        host_name
        )
        
    await update_status_message(ch, None, img)
    return await interaction.followup.send(f"⏱️ Match time set: {dt.strftime('%Y-%m-%d %H:%M %Z')}", ephemeral=False)

@bot.tree.command(
    name="match_decide",
    description="Winner chooses host or first ban"
)
@app_commands.describe(choice="Select 'ban' to ban first, or 'host' to choose hosting")
async def match_decide(
    interaction: discord.Interaction,
    choice: Literal["ban","host"]
) -> None:
    """Handle the coin flip decision: 'ban' means flip winner bans first; 'host' means other hosts and bans second."""
    ch = interaction.channel_id
    # Validate state
    if ch not in ongoing_bans or channel_flip.get(ch) is None or channel_decision.get(ch) is not None:
        return await interaction.response.send_message("❌ Invalid state.", ephemeral=True)
    # Acknowledge
    await interaction.response.defer(ephemeral=True)
    # Record decision
    channel_decision[ch] = choice
    flip = channel_flip[ch]  # internal key 'team_a' or 'team_b'
    # Set next turn based on choice
    if choice == "ban":
        # flip winner bans first
        match_turns[ch] = flip
    else:
        # host: the other team bans first
        match_turns[ch] = "team_b" if flip == "team_a" else "team_a"
    save_state()
    # Regenerate and update image
    img = create_ban_status_image(
        load_maplist(),
        ongoing_bans[ch],
        None, None,
        channel_mode[ch],
        channel_flip[ch],
        choice,
        match_turns[ch],
        match_times.get(ch),
        False
    )
    await update_status_message(ch, None, img)
    # Confirmation
    await interaction.followup.send(f"✅ Decision recorded: {choice}", ephemeral=True)

@bot.tree.command(
    name="match_delete",
    description="Delete current match"
)
async def match_delete(
    interaction: discord.Interaction
) -> None:
    await interaction.response.defer(ephemeral=True)
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return await interaction.followup.send("❌ No match to delete.", ephemeral=True)
    await cleanup_match(ch)
    return await interaction.followup.send("✅ Match deleted.", ephemeral=True)

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
    load_state()
    print("Bot ready.")

bot.run(os.getenv("DISCORD_TOKEN"))