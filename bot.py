import os
import json
import random
import asyncio
from typing import Literal, Tuple, List, Optional

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

# ─── In-Memory State (populated from disk) ───────────────────────────────────────
ongoing_bans: dict[int, dict[str, dict[str, List[str]]]] = {}
match_turns:    dict[int, str]               = {}
channel_teams:  dict[int, Tuple[str,str]]    = {}
channel_messages:dict[int, int]              = {}
channel_flip:   dict[int, str]               = {}
channel_decision:dict[int, Optional[str]]    = {}
channel_mode:   dict[int, str]               = {}

# ─── Persistence Helpers ────────────────────────────────────────────────────────
def load_state():
    global ongoing_bans, match_turns, channel_teams, channel_messages
    global channel_flip, channel_decision, channel_mode
    if not os.path.isfile(STATE_FILE):
        return
    try:
        data = json.load(open(STATE_FILE))
    except json.JSONDecodeError:
        save_state()
        return
    ongoing_bans     = {int(k):v for k,v in data.get("ongoing_bans",{}).items()}
    match_turns      = {int(k):v for k,v in data.get("match_turns",{}).items()}
    channel_teams    = {int(k):tuple(v) for k,v in data.get("channel_teams",{}).items()}
    channel_messages = {int(k):v for k,v in data.get("channel_messages",{}).items()}
    channel_flip     = {int(k):v for k,v in data.get("channel_flip",{}).items()}
    channel_decision = {int(k):v for k,v in data.get("channel_decision",{}).items()}
    channel_mode     = {int(k):v for k,v in data.get("channel_mode",{}).items()}

def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump({
            "ongoing_bans":     {str(k):v for k,v in ongoing_bans.items()},
            "match_turns":      {str(k):v for k,v in match_turns.items()},
            "channel_teams":    {str(k):list(v) for k,v in channel_teams.items()},
            "channel_messages": {str(k):v for k,v in channel_messages.items()},
            "channel_flip":     {str(k):v for k,v in channel_flip.items()},
            "channel_decision": {str(k):v for k,v in channel_decision.items()},
            "channel_mode":     {str(k):v for k,v in channel_mode.items()},
        }, f, indent=2)

async def cleanup_match(ch: int):
    for d in (ongoing_bans, match_turns, channel_teams,
              channel_messages, channel_flip, channel_decision, channel_mode):
        d.pop(ch, None)
    save_state()
    try:
        os.remove("ban_status.png")
    except FileNotFoundError:
        pass

# ─── Config & Maplist ───────────────────────────────────────────────────────────
def load_config()  -> dict: return json.load(open("teammap.json"))
def load_maplist() -> List[dict]: return json.load(open("maplist.json"))["maps"]

def determine_ban_option(a: str, b: str, cfg: dict) -> str:
    return cfg.get("region_pairings", {}).get(a, {}).get(b, "ExtraBan")

# ─── Image Generation w/ Auto-Fit & Extra Padding ───────────────────────────────
def create_ban_status_image(
    map_list: List[dict],
    bans: dict[str, dict[str, List[str]]],
    team_a_label: str,
    team_b_label: str,
    pairing_mode: str,
    flip_winner: Optional[str],
    decision_choice: Optional[str],
    current_turn: Optional[str]
) -> str:
    row_fs, hdr_fs = 168, 240
    font_paths = [
        "arialbd.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
    row_font = hdr_font = None
    for p in font_paths:
        try:
            row_font = ImageFont.truetype(p, row_fs)
            hdr_font = ImageFont.truetype(p, hdr_fs)
            break
        except:
            continue
    if not row_font:
        row_font = ImageFont.load_default()
        hdr_font = ImageFont.load_default()

    def measure(fnt, txt):
        b = fnt.getbbox(txt)
        return b[2] - b[0], b[3] - b[1]

    # Measure sizes
    side_sizes = [measure(row_font, s) for s in ("Allied", "Axis")]
    max_side_w, max_side_h = max(w for w,h in side_sizes), max(h for w,h in side_sizes)
    map_sizes  = [measure(row_font, m["name"]) for m in map_list] + [measure(hdr_font, "Maps")]
    max_map_w, max_map_h = max(w for w,h in map_sizes), max(h for w,h in map_sizes)

    # Banner text
    flip_lbl = flip_winner or "TBD"
    if pairing_mode == "ExtraBan":
        first_lbl, host_field = flip_lbl, "Middle ground rules in effect."
    else:
        if decision_choice is None:
            first_lbl, host_field = "TBD", f"{flip_lbl} chooses host"
        elif decision_choice == "ban":
            first_lbl = flip_lbl
            other = team_b_label if flip_lbl == team_a_label else team_a_label
            host_field = f"Host: {other}"
        else:
            other = team_b_label if flip_lbl == team_a_label else team_a_label
            first_lbl = other
            host_field = f"Host: {flip_lbl}"
    line1 = f"Flip Winner: {flip_lbl}   |   First Ban: {first_lbl}   |   {host_field}"
    line2 = f"Current Turn: {current_turn or 'TBD'}"
    b1_w, b1_h = measure(hdr_font, line1)
    b2_w, b2_h = measure(hdr_font, line2)

    pad_x, pad_y = hdr_fs//2, hdr_fs//4

    # Double-pad the Allied/Axis columns
    side_w = max(max_side_w, measure(hdr_font, "Allied")[0]) + pad_x * 2
    map_w  = max(max_map_w, measure(hdr_font, "Maps")[0]) + pad_x * 2
    row_h  = max(max_side_h, max_map_h) + pad_y * 2
    h1     = hdr_fs + pad_y
    h2     = hdr_fs + pad_y
    banner_h1 = b1_h + pad_y*2
    banner_h2 = b2_h + pad_y*2
    banner_h  = banner_h1 + banner_h2

    total_w = side_w*4 + map_w
    total_w = max(total_w, b1_w + pad_x*2, b2_w + pad_x*2)
    map_w    = total_w - side_w*4
    height   = banner_h + h1 + h2 + len(map_list)*row_h + pad_y

    img  = Image.new("RGB", (total_w, height), (240,240,240))
    draw = ImageDraw.Draw(img)
    y = 0

    # Banner
    draw.rectangle([0,y,total_w,y+banner_h], fill=(220,220,255), outline="black")
    draw.text((total_w//2, y+banner_h1//2),          line1, font=hdr_font, anchor="mm", fill="black")
    draw.text((total_w//2, y+banner_h1+banner_h2//2), line2, font=hdr_font, anchor="mm", fill="black")
    y += banner_h

    # Header row 1: Team A | Maps | Team B
    draw.rectangle([0,y,2*side_w,y+h1], fill=(200,200,200), outline="black")
    draw.text((side_w, y+h1//2),             team_a_label, font=hdr_font, anchor="mm", fill="black")
    draw.rectangle([2*side_w,y,2*side_w+map_w,y+h1], fill=(200,200,200), outline="black")
    draw.text((2*side_w+map_w//2, y+h1//2),  "Maps",      font=hdr_font, anchor="mm", fill="black")
    draw.rectangle([2*side_w+map_w,y,total_w,y+h1], fill=(200,200,200), outline="black")
    draw.text((2*side_w+map_w+side_w, y+h1//2), team_b_label, font=hdr_font, anchor="mm", fill="black")
    y += h1

    # Header row 2: Allied/Axis labels
    labels = ["Allied","Axis","","Allied","Axis"]
    widths = [side_w, side_w, map_w, side_w, side_w]
    x = 0
    for w, lab in zip(widths, labels):
        draw.rectangle([x,y,x+w,y+h2], fill=(220,220,220), outline="black")
        if lab:
            draw.text((x+w//2, y+h2//2), lab, font=hdr_font, anchor="mm", fill="black")
        x += w
    y += h2

    # Map rows
    for m in map_list:
        name = m["name"]
        tb   = bans[name]
        x = 0

        # Team A sides
        for side in ("Allied","Axis"):
            if side in tb["team_a"]["manual"]:
                c = (255,0,0)
            elif side in tb["team_a"]["auto"]:
                c = (255,165,0)
            else:
                c = (255,255,255)
            draw.rectangle([x,y,x+side_w,y+row_h], fill=c, outline="black")
            draw.text((x+side_w//2, y+row_h//2), side, font=row_font, anchor="mm", fill="black")
            x += side_w

        # Map cell (middle)
        draw.rectangle([x,y,x+map_w,y+row_h], fill=(240,240,240), outline="black")
        draw.text((x+map_w//2, y+row_h//2), name, font=row_font, anchor="mm", fill="black")
        x += map_w

        # Team B sides
        for side in ("Allied","Axis"):
            if side in tb["team_b"]["manual"]:
                c = (255,0,0)
            elif side in tb["team_b"]["auto"]:
                c = (255,165,0)
            else:
                c = (255,255,255)
            draw.rectangle([x,y,x+side_w,y+row_h], fill=c, outline="black")
            draw.text((x+side_w//2, y+row_h//2), side, font=row_font, anchor="mm", fill="black")
            x += side_w

        y += row_h

    path = "ban_status.png"
    img.save(path)
    return path

# ─── Message-Editing Helper ─────────────────────────────────────────────────────
async def update_status_message(channel_id:int, content:Optional[str], image_path:str):
    load_state()
    chan = bot.get_channel(channel_id)
    if not chan: return
    msg_id = channel_messages.get(channel_id)
    file   = discord.File(image_path)
    if msg_id:
        try:
            m = await chan.fetch_message(msg_id)
            await m.edit(content=content, attachments=[file])
            return
        except discord.NotFound:
            pass
    m = await chan.send(content=content, file=file)
    channel_messages[channel_id] = m.id
    save_state()

async def delete_later(msg:discord.Message, delay:float):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass

# ─── Autocomplete ──────────────────────────────────────────────────────────────
async def map_autocomplete(interaction:discord.Interaction, current:str):
    load_state()
    ch = interaction.channel_id
    if ch not in ongoing_bans: return []
    team = match_turns.get(ch); opts=[]
    if team:
        for m in load_maplist():
            tb = ongoing_bans[ch][m["name"]][team]
            if len(tb["manual"])+len(tb["auto"])<2 and current.lower() in m["name"].lower():
                opts.append(app_commands.Choice(name=m["name"], value=m["name"]))
    return opts[:25]

async def side_autocomplete(interaction:discord.Interaction, current:str):
    load_state()
    ch = interaction.channel_id
    if ch not in ongoing_bans: return []
    sel = interaction.namespace.map_name
    team = match_turns.get(ch); opts=[]
    if team and sel in ongoing_bans[ch]:
        tb = ongoing_bans[ch][sel][team]
        for s in ("Allied","Axis"):
            if s not in tb["manual"] and s not in tb["auto"] and current.lower() in s.lower():
                opts.append(app_commands.Choice(name=s, value=s))
    return opts[:25]

# ─── Slash Commands ────────────────────────────────────────────────────────────

@bot.tree.command(name="match_create", description="Create a new match")
async def match_create(
    interaction:discord.Interaction,
    team_a:discord.Role,
    team_b:discord.Role,
    title:str,
    description:str="No description provided"
):
    load_state()
    ch = interaction.channel_id
    if ch in ongoing_bans:
        await interaction.response.defer(ephemeral=True)
        return await interaction.followup.send("❌ Match active here; delete first.", ephemeral=True)

    await interaction.response.defer()

    cfg, maps = load_config(), load_maplist()
    a,b = team_a.name, team_b.name
    ra,rb = cfg["team_regions"].get(a,"Unknown"), cfg["team_regions"].get(b,"Unknown")
    mode = determine_ban_option(ra, rb, cfg)

    winner = random.choice(["team_a","team_b"])
    channel_flip[ch]     = winner
    channel_mode[ch]     = mode
    channel_decision[ch] = "ban" if mode=="ExtraBan" else None
    first_turn           = winner if mode=="ExtraBan" else None

    ongoing_bans[ch]   = {m["name"]:{"team_a":{"manual":[],"auto":[]},
                                     "team_b":{"manual":[],"auto":[]}}
                         for m in maps}
    match_turns[ch]    = first_turn
    channel_teams[ch]  = (a,b)
    save_state()

    flip_lbl = a if winner=="team_a" else b
    cur_lbl  = a if first_turn=="team_a" else (b if first_turn=="team_b" else None)
    img = create_ban_status_image(maps, ongoing_bans[ch],
                                  a, b,
                                  mode, flip_lbl,
                                  channel_decision[ch], cur_lbl)

    follow = await interaction.followup.send(
        f"**Match Created**\nTitle: {title}\nTeam A: {a} ({ra})\n"
        f"Team B: {b} ({rb})\nMode: {mode}\n{description}",
        file=discord.File(img)
    )
    channel_messages[ch] = follow.id
    save_state()

@app_commands.autocomplete(map_name=map_autocomplete, side=side_autocomplete)
@bot.tree.command(name="ban_map", description="Ban a map side")
async def ban_map(
    interaction:discord.Interaction,
    map_name:str,
    side:str
):
    load_state()
    await interaction.response.defer()
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return await interaction.followup.send("❌ No match; use `/match_create`.", ephemeral=True)
    if channel_mode[ch]=="DetermineHost" and channel_decision[ch] is None:
        return await interaction.followup.send("❌ Waiting for `/match_decide`.", ephemeral=True)

    tk = match_turns[ch]
    if not tk:
        return await interaction.followup.send("❌ Turn order unset.", ephemeral=True)
    role_name = channel_teams[ch][0] if tk=="team_a" else channel_teams[ch][1]
    if role_name not in [r.name for r in interaction.user.roles]:
        return await interaction.followup.send("❌ Not your turn.", ephemeral=True)

    combos_pre = [
        (m,t,s)
        for m,tb in ongoing_bans[ch].items()
        for t in ("team_a","team_b")
        for s in ("Allied","Axis")
        if s not in tb[t]["manual"] and s not in tb[t]["auto"]
    ]
    if len(combos_pre)==2 and combos_pre[0][0]==combos_pre[1][0]:
        img = create_ban_status_image(
            load_maplist(), ongoing_bans[ch],
            *channel_teams[ch],
            channel_mode[ch],
            channel_teams[ch][0] if channel_flip[ch]=="team_a" else channel_teams[ch][1],
            channel_decision[ch], None
        )
        m,t1,s1 = combos_pre[0]; _,t2,s2 = combos_pre[1]
        tm1 = channel_teams[ch][0] if t1=="team_a" else channel_teams[ch][1]
        tm2 = channel_teams[ch][0] if t2=="team_a" else channel_teams[ch][1]
        content = f"🏁 Ban complete!\n- Map: {m}\n- {tm1} = {s1}\n- {tm2} = {s2}"
        await update_status_message(ch, content, img)
        return await interaction.followup.send("✅ Already complete.", ephemeral=True)

    other = "team_b" if tk=="team_a" else "team_a"
    tb    = ongoing_bans[ch][map_name]
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
    cur_lbl = None if len(combos_post)==2 and combos_post[0][0]==combos_post[1][0] else (
        channel_teams[ch][0] if match_turns[ch]=="team_a" else channel_teams[ch][1]
    )
    img = create_ban_status_image(
        load_maplist(), ongoing_bans[ch],
        channel_teams[ch][0], channel_teams[ch][1],
        channel_mode[ch],
        channel_teams[ch][0] if channel_flip[ch]=="team_a" else channel_teams[ch][1],
        channel_decision[ch], cur_lbl
    )

    if len(combos_post)==2 and combos_post[0][0]==combos_post[1][0]:
        m,t1,s1 = combos_post[0]; _,t2,s2 = combos_post[1]
        tm1 = channel_teams[ch][0] if t1=="team_a" else channel_teams[ch][1]
        tm2 = channel_teams[ch][0] if t2=="team_a" else channel_teams[ch][1]
        content = f"🏁 Ban complete!\n- Map: {m}\n- {tm1} = {s1}\n- {tm2} = {s2}"
    else:
        content = None

    await update_status_message(ch, content, img)
    conf = await interaction.followup.send("✅ Your ban has been recorded.")
    asyncio.create_task(delete_later(conf, 5.0))

@bot.tree.command(name="match_decide", description="Winner chooses host or first ban")
async def match_decide(
    interaction:discord.Interaction,
    choice:Literal["ban","host"]
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
        f"✅ Chose **{'First Ban' if choice=='ban' else 'Host'}**; first ban: "
        f"**{a_lbl if match_turns[ch]=='team_a' else b_lbl}**.",
        ephemeral=True
    )

@bot.tree.command(name="match_delete", description="Delete the current match")
async def match_delete(interaction:discord.Interaction):
    load_state()
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return await interaction.response.send_message("❌ No active match.", ephemeral=True)
    await cleanup_match(ch)
    await interaction.response.send_message("✅ Deleted.", ephemeral=True)

@bot.event
async def on_ready():
    load_state()
    await bot.tree.sync()
    print("Bot ready; matches:", list(ongoing_bans.keys()))

bot.run(os.getenv("DISCORD_TOKEN"))
