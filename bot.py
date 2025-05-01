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
    "state_file":       "state.json",
    "teammap_file":     "teammap.json",
    "maplist_file":     "maplist.json",
    "output_image":     "ban_status.png",
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

# ─── Bot Setup ──────────────────────────────────────────────────────────────────
load_dotenv()
bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
bot.intents.message_content = True

# Canvas-wide in-memory state
ongoing_bans:      dict[int, dict[str, dict[str, list[str]]]] = {}
match_turns:       dict[int, str]                            = {}
match_times:       dict[int, str]                            = {}
channel_teams:     dict[int, Tuple[str, str]]                = {}
channel_messages:  dict[int, int]                            = {}
channel_flip:      dict[int, str]                            = {}
channel_decision:  dict[int, Optional[str]]                  = {}
channel_mode:      dict[int, str]                            = {}

STATE_FILE = CONFIG["state_file"]

# ─── Helpers: Persistence ────────────────────────────────────────────────────────
def load_state():
    global ongoing_bans, match_turns, channel_teams, channel_messages
    global channel_flip, channel_decision, channel_mode
    if not os.path.isfile(STATE_FILE):
        return
    try:
        data = json.load(open(STATE_FILE))
    except json.JSONDecodeError:
        #save_state()
        return
    ongoing_bans.update({int(k): v for k, v in data.get("ongoing_bans", {}).items()})
    match_turns.update({int(k): v for k, v in data.get("match_turns", {}).items()})
    match_times.update({int(k): v for k, v in data.get("match_times", {}).items()})
    channel_teams.update({int(k): tuple(v) for k, v in data.get("channel_teams", {}).items()})
    channel_messages.update({int(k): v for k, v in data.get("channel_messages", {}).items()})
    channel_flip.update({int(k): v for k, v in data.get("channel_flip", {}).items()})
    channel_decision.update({int(k): v for k, v in data.get("channel_decision", {}).items()})
    channel_mode.update({int(k): v for k, v in data.get("channel_mode", {}).items()})

def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump({
            "ongoing_bans":     {str(k):v for k,v in ongoing_bans.items()},
            "match_turns":      {str(k):v for k,v in match_turns.items()},
            "match_times":      {str(k): v for k, v in match_times.items()},
            "channel_teams":    {str(k):list(v) for k,v in channel_teams.items()},
            "channel_messages": {str(k):v for k,v in channel_messages.items()},
            "channel_flip":     {str(k):v for k,v in channel_flip.items()},
            "channel_decision": {str(k):v for k,v in channel_decision.items()},
            "channel_mode":     {str(k):v for k,v in channel_mode.items()},
        }, f, indent=2)

# ─── Helpers: Config Loaders & Ban Logic ─────────────────────────────────────────

# ─── Config Loaders ─────────────────────────────────────────────────────────────
def load_teammap() -> dict:
    return json.load(open(CONFIG["teammap_file"]))
def load_maplist() -> List[dict]:
    return json.load(open(CONFIG["maplist_file"]))["maps"]
    
async def cleanup_match(ch: int):
    for d in (
        ongoing_bans, match_turns, channel_teams,
        channel_messages, channel_flip, channel_decision, channel_mode
    ):
        d.pop(ch, None)
    save_state()
    try:
        os.remove(CONFIG["output_image"])
    except FileNotFoundError:
        pass
       
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

# ─── Helpers: Image Generation ─────────────────────────────────────────────────
def create_ban_status_image(
    maps: List[dict],
    bans: dict[str, dict[str, list[str]]],
    team_a: str, team_b: str,
    mode: str, flip_winner: str,
    decision_choice: Optional[str], current_turn: Optional[str],
    match_time_iso: Optional[str] = None
) -> str:
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
    font_paths = CONFIG["font_paths"]

    row_font = hdr_font = None
    for fp in font_paths:
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
    line2 = f"Current Turn: {current_turn or 'TBD'}"
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
    return out_path

# ─── Helpers: Messaging ─────────────────────────────────────────────────────────
async def update_status_message(ch_id: int, content: Optional[str], img_path: str):
    chan = bot.get_channel(ch_id)
    if chan:
        msg_id = channel_messages.get(ch_id)
        file   = discord.File(img_path)
        if msg_id:
            try:
                m = await chan.fetch_message(msg_id)
                await m.edit(content=content, attachments=[file])
                return
            except discord.NotFound:
                pass
        m = await chan.send(content=content, file=file)
        channel_messages[ch_id] = m.id
        save_state()

async def delete_later(msg: discord.Message, delay: float):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass

@bot.event
async def on_ready() -> None:
    load_state()             # one-time load
    # Sync only to our test guild for instant registration
    await bot.tree.sync(guild=discord.Object(id=1366830976369557654))    # register commands
    print("Bot ready; active matches:", list(ongoing_bans.keys()))

# ─── Autocomplete Handlers for ban_map ─────────────────────────────────────────
async def map_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    matches = [m["name"] for m in json.load(open(CONFIG["maplist_file"]))["maps"]
               if current.lower() in m["name"].lower()]
    return [app_commands.Choice(name=m, value=m) for m in matches[:25]]

async def side_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    sides = [s for s in ("Allied", "Axis") if current.lower() in s.lower()]
    return [app_commands.Choice(name=s, value=s) for s in sides[:25]]

# ─── /ban_map Command ───────────────────────────────────────────────────────────
@bot.tree.command(name="ban_map", description="Ban a map for a given side",guild=discord.Object(id=1366830976369557654))
@app_commands.describe(map_name="Map to ban", side="Allied or Axis")
@app_commands.autocomplete(map_name=map_autocomplete, side=side_autocomplete)
async def ban_map(
    interaction: discord.Interaction,
    map_name: str,
    side: str
):
    load_state()
    await interaction.response.defer()
    ch = interaction.channel_id
    
    if ch not in ongoing_bans:
        await interaction.followup.send("❌ No active match here.", ephemeral=True)
        return
    if channel_mode[ch] == "DetermineHost" and channel_decision[ch] is None:
        await interaction.followup.send("❌ Waiting for host decision.", ephemeral=True)
        return

    tk = match_turns[ch]
    if not tk:
        await interaction.followup.send("❌ Turn order not set.", ephemeral=True)
        return
    role = channel_teams[ch][0] if tk == "team_a" else channel_teams[ch][1]
    if role not in [r.name for r in interaction.user.roles]:
        await interaction.followup.send("❌ Not your turn.", ephemeral=True)
        return

    combos_pre = [
        (m,t,s)
        for m,tb in ongoing_bans[ch].items()
        for t in ("team_a","team_b")
        for s in ("Allied","Axis")
        if s not in tb[t]["manual"] and s not in tb[t]["auto"]
    ]
    if len(combos_pre) == 2 and combos_pre[0][0] == combos_pre[1][0]:
        img = create_ban_status_image(
            load_maplist(), ongoing_bans[ch],
            *channel_teams[ch],
            channel_mode[ch],
            channel_teams[ch][0] if channel_flip[ch]=="team_a" else channel_teams[ch][1],
            channel_decision[ch], None
        )
        content = (
            f"🏁 Ban complete!\n"
            f"- Map: {combos_pre[0][0]}\n"
            f"- {channel_teams[ch][0] if combos_pre[0][1]=='team_a' else channel_teams[ch][1]} = {combos_pre[0][2]}\n"
            f"- {channel_teams[ch][0] if combos_pre[1][1]=='team_a' else channel_teams[ch][1]} = {combos_pre[1][2]}"
        )
        await update_status_message(ch, content, img)

        poll = await interaction.channel.send(
            f"📊 **Who will win the match?**\n"
            f"🅰️ {channel_teams[ch][0]}\n"
            f"🅱️ {channel_teams[ch][1]}"
        )
        await poll.add_reaction("🅰️")
        await poll.add_reaction("🅱️")

        await interaction.followup.send("✅ Ban already complete and poll posted.", ephemeral=True)
        return

    other = "team_b" if tk=="team_a" else "team_a"
    tb = ongoing_bans[ch][map_name]
    tb[tk]["manual"].append(side)
    tb[other]["auto"].append("Axis" if side=="Allied" else "Allied")
    match_turns[ch] = other
    save_state()

    combos_post = [
        (m,t,s)
        for m,tb in ongoing_bans[ch].items()
        for t in ("team_a","team_b")
        for s in ("Allied","Axis")
        if s not in tb[t]["manual"] and s not in tb[t]["auto"]
    ]
    is_complete = len(combos_post)==2 and combos_post[0][0]==combos_post[1][0]

    content = None
    if is_complete:
        content = (
            f"🏁 Ban complete!\n"
            f"- Map: {combos_post[0][0]}\n"
            f"- {channel_teams[ch][0] if combos_post[0][1]=='team_a' else channel_teams[ch][1]} = {combos_post[0][2]}\n"
            f"- {channel_teams[ch][0] if combos_post[1][1]=='team_a' else channel_teams[ch][1]} = {combos_post[1][2]}"
        )
    cur_lbl = None if is_complete else (
        channel_teams[ch][0] if match_turns[ch]=="team_a" else channel_teams[ch][1]
    )
    img = create_ban_status_image(
        load_maplist(), ongoing_bans[ch],
        channel_teams[ch][0], channel_teams[ch][1],
        channel_mode[ch],
        channel_teams[ch][0] if channel_flip[ch]=="team_a" else channel_teams[ch][1],
        channel_decision[ch], cur_lbl
    )
    await update_status_message(ch, content, img)

    if is_complete:
        poll = await interaction.channel.send(
            f"📊 **Who will win the match?**\n"
            f"🅰️ {channel_teams[ch][0]}\n"
            f"🅱️ {channel_teams[ch][1]}"
        )
        await poll.add_reaction("🅰️")
        await poll.add_reaction("🅱️")
        await interaction.followup.send("✅ Ban complete and poll posted.", ephemeral=True)
    else:
        conf = await interaction.followup.send("✅ Your ban has been recorded.", ephemeral=True)
        asyncio.create_task(delete_later(conf, 5.0))

# ─── /match_create Command ───────────────────────────────────────────────────────
@bot.tree.command(name="match_create", description="Create a new match",guild=discord.Object(id=1366830976369557654))
async def match_create(
    interaction: discord.Interaction,
    team_a: discord.Role,
    team_b: discord.Role,
    title: str,
    description: str = "No description provided"
):
    load_state()
    ch = interaction.channel_id
    if ch in ongoing_bans:
        await interaction.response.send_message("❌ Match already active here.", ephemeral=True)
        return
    await interaction.response.defer()

    cfg, maps = load_teammap(), load_maplist()
    a, b = team_a.name, team_b.name
    ra, rb = cfg["team_regions"].get(a, "Unknown"), cfg["team_regions"].get(b, "Unknown")
    mode = determine_ban_option(ra, rb, cfg)

    winner = random.choice(["team_a", "team_b"])
    channel_flip[ch]     = winner
    channel_mode[ch]     = mode
    channel_decision[ch] = "ban" if mode == "ExtraBan" else None
    first_turn           = winner if mode == "ExtraBan" else None

    ongoing_bans[ch] = {
        m["name"]: {"team_a": {"manual": [], "auto": []},
                    "team_b": {"manual": [], "auto": []}}
        for m in maps
    }
    match_turns[ch]  = first_turn
    channel_teams[ch] = (a, b)
    save_state()

    flip_lbl = a if winner == "team_a" else b
    cur_lbl  = a if first_turn == "team_a" else (b if first_turn == "team_b" else None)
    img = create_ban_status_image(maps, ongoing_bans[ch], a, b, mode, flip_lbl, channel_decision[ch], cur_lbl)

    follow = await interaction.followup.send(
        f"**Match Created**\nTitle: {title}\n"
        f"Team A: {a} ({ra})\nTeam B: {b} ({rb})\nMode: {mode}\n{description}",
        file=discord.File(img)
    )
    channel_messages[ch] = follow.id
    save_state()
    
# ─── /match_time Command ───────────────────────────────────────────────────────
@bot.tree.command(name="match_time", description="Set match date/time",guild=discord.Object(id=1366830976369557654))
@app_commands.describe(time="ISO8601 datetime with timezone")
async def match_time_cmd(
    interaction: discord.Interaction,
    time: str
) -> None:
    await interaction.response.defer(ephemeral=True)
    ch = interaction.channel_id
    if ch not in ongoing_bans or not is_ban_complete(ch):
        return await interaction.followup.send("❌ Ban phase not complete.", ephemeral=True)
    try:
        dt_local = parser.isoparse(time).astimezone(pytz.timezone(CONFIG["user_timezone"]))
        match_times[ch] = dt_local.isoformat()
        save_state()
    except Exception as e:
        return await interaction.followup.send(f"❌ Invalid datetime: {e}", ephemeral=True)
    img = create_ban_status_image(
        json.load(open(CONFIG["maplist_file"]))["maps"],
        ongoing_bans[ch], *channel_teams[ch], channel_mode[ch], channel_flip[ch], channel_decision[ch], match_times[ch]
    )
    await update_status_message(ch, f"⏱️ Match set: {dt_local.strftime('%Y-%m-%d %H:%M %Z')}", img)

# ─── /match_decide Command ───────────────────────────────────────────────────────
@bot.tree.command(name="match_decide", description="Winner chooses host or first ban",guild=discord.Object(id=1366830976369557654))
async def match_decide(
    interaction: discord.Interaction,
    choice: Literal["ban","host"]
):
    load_state()
    ch = interaction.channel_id
    if ch not in ongoing_bans or channel_flip[ch] is None:
        return await interaction.response.send_message("❌ No decision.", ephemeral=True)
    if channel_decision[ch] is not None:
        return await interaction.response.send_message("❌ Already decided.", ephemeral=True)
    winner = channel_flip[ch]
    wl = channel_teams[ch][0] if winner=="team_a" else channel_teams[ch][1]
    if wl not in [r.name for r in interaction.user.roles]:
        return await interaction.response.send_message("❌ Only flip winner.", ephemeral=True)

    channel_decision[ch] = choice
    match_turns[ch]      = winner if choice=="ban" else ("team_b" if winner=="team_a" else "team_a")
    save_state()

    a_lbl,b_lbl = channel_teams[ch]
    img = create_ban_status_image(
        load_maplist(), ongoing_bans[ch],
        a_lbl, b_lbl,
        channel_mode[ch],
        a_lbl if winner=="team_a" else b_lbl,
        choice,
        a_lbl if match_turns[ch]=="team_a" else b_lbl
    )
    await update_status_message(ch, None, img)
    await interaction.response.send_message(
        f"✅ Chose **{'First Ban' if choice=='ban' else 'Host'}**; first ban: **{a_lbl if match_turns[ch]=='team_a' else b_lbl}**.",
        ephemeral=True
    )
    
# ─── /match_delete Command ───────────────────────────────────────────────────────
@bot.tree.command(name="match_delete", description="Delete the current match",guild=discord.Object(id=1366830976369557654))
async def match_delete(interaction: discord.Interaction):
    load_state()
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return await interaction.response.send_message("❌ No active match.", ephemeral=True)
    await cleanup_match(ch)
    await interaction.response.send_message("✅ Deleted.", ephemeral=True)
    
# ─── Error Handler ─────────────────────────────────────────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception) -> None:
    if isinstance(error, discord.errors.NotFound):
        return  # ignore stale
    raise error

# ─── Run Bot ───────────────────────────────────────────────────────────────────
bot.run(os.getenv("DISCORD_TOKEN"))
