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

# ─── In-Memory State ────────────────────────────────────────────────────────────
ongoing_bans: dict[int, dict[str, dict[str, List[str]]]] = {}
match_turns: dict[int, str]                = {}  # "team_a" or "team_b"
channel_teams: dict[int, Tuple[str,str]]   = {}  # channel_id → (team_a, team_b)
channel_messages: dict[int, int]           = {}  # channel_id → status msg id
channel_flip: dict[int, str]               = {}  # channel_id → "team_a"/"team_b"
channel_decision: dict[int, Optional[str]] = {}  # channel_id → "ban"/"host"/None
channel_mode: dict[int, str]               = {}  # channel_id → "ExtraBan"/"DetermineHost"

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
    with open(STATE_FILE,"w") as f:
        json.dump({
            "ongoing_bans":     {str(k):v for k,v in ongoing_bans.items()},
            "match_turns":      {str(k):v for k,v in match_turns.items()},
            "channel_teams":    {str(k):list(v) for k,v in channel_teams.items()},
            "channel_messages": {str(k):v for k,v in channel_messages.items()},
            "channel_flip":     {str(k):v for k,v in channel_flip.items()},
            "channel_decision": {str(k):v for k,v in channel_decision.items()},
            "channel_mode":     {str(k):v for k,v in channel_mode.items()},
        }, f, indent=2)

async def cleanup_match(ch:int):
    for d in (ongoing_bans, match_turns, channel_teams,
              channel_messages, channel_flip, channel_decision, channel_mode):
        d.pop(ch, None)
    save_state()
    try: os.remove("ban_status.png")
    except: pass

# ─── Config & Maplist ───────────────────────────────────────────────────────────
def load_config()  -> dict: return json.load(open("teammap.json"))
def load_maplist() -> List[dict]: return json.load(open("maplist.json"))["maps"]

# ─── Region Pairing & Mode ──────────────────────────────────────────────────────
def determine_ban_option(a:str, b:str, cfg:dict) -> str:
    return cfg.get("region_pairings",{}).get(a,{}).get(b,"ExtraBan")

# ─── Image Generation ───────────────────────────────────────────────────────────
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
    # 2× larger fonts for maximum legibility
    row_fs, hdr_fs = 56, 80
    try:
        row_font = ImageFont.truetype("arialbd.ttf", row_fs)
        hdr_font = ImageFont.truetype("arialbd.ttf", hdr_fs)
    except:
        row_font = ImageFont.load_default()
        hdr_font = ImageFont.load_default()

    # two-line banner
    banner_h1 = hdr_fs + 20
    banner_h2 = hdr_fs + 20
    banner_h  = banner_h1 + banner_h2

    h1  = hdr_fs + 16
    h2  = hdr_fs + 12
    row_h = row_fs + 12

    # Widened to 1600px, map column 600px
    total_w, map_w = 1600, 600
    sub_w = (total_w - map_w) // 4
    cols  = [sub_w, sub_w, map_w, sub_w, sub_w]
    height = banner_h + h1 + h2 + len(map_list)*row_h + 10

    # final combo detection
    combos = [
        (m,t,s)
        for m,tb in bans.items()
        for t in ("team_a","team_b")
        for s in ("Allied","Axis")
        if s not in tb[t]["manual"] and s not in tb[t]["auto"]
    ]
    final_combo = combos if len(combos)==2 and combos[0][0]==combos[1][0] else None

    # build header lines
    flip_lbl = flip_winner or "TBD"
    if pairing_mode == "ExtraBan":
        first_lbl  = flip_lbl
        host_field = "Middle ground rules in effect."
    else:
        if decision_choice is None:
            first_lbl  = "TBD"
            host_field = f"{flip_lbl} chooses host"
        elif decision_choice == "ban":
            first_lbl  = flip_lbl
            other      = team_b_label if flip_lbl==team_a_label else team_a_label
            host_field = f"Host: {other}"
        else:
            other      = team_b_label if flip_lbl==team_a_label else team_a_label
            first_lbl  = other
            host_field = f"Host: {flip_lbl}"
    line1 = f"Flip Winner: {flip_lbl}   |   First Ban: {first_lbl}   |   {host_field}"
    line2 = f"Current Turn: {current_turn or 'TBD'}"

    img = Image.new("RGB",(total_w,height),(240,240,240))
    draw = ImageDraw.Draw(img)
    y = 0

    # draw banner background
    draw.rectangle([0,y,total_w,y+banner_h], fill=(220,220,255), outline="black")
    # line1
    draw.text((total_w//2, y + banner_h1//2),
              line1, font=hdr_font, anchor="mm", fill="black")
    # line2
    draw.text((total_w//2, y + banner_h1 + banner_h2//2),
              line2, font=hdr_font, anchor="mm", fill="black")
    y += banner_h

    # header row 1
    draw.rectangle([0,y,2*sub_w,y+h1], fill=(200,200,200), outline="black")
    draw.text((sub_w, y+h1//2), team_a_label, font=hdr_font, anchor="mm", fill="black")
    draw.rectangle([2*sub_w,y,2*sub_w+map_w,y+h1], fill=(200,200,200), outline="black")
    draw.text((2*sub_w+map_w//2, y+h1//2), "Maps", font=hdr_font, anchor="mm", fill="black")
    draw.rectangle([2*sub_w+map_w,y,total_w,y+h1], fill=(200,200,200), outline="black")
    draw.text((2*sub_w+map_w+sub_w, y+h1//2), team_b_label, font=hdr_font, anchor="mm", fill="black")
    y += h1

    # header row 2
    labels = ["Allied","Axis","","Allied","Axis"]
    x = 0
    for w, lab in zip(cols, labels):
        draw.rectangle([x,y,x+w,y+h2], fill=(220,220,220), outline="black")
        if lab:
            draw.text((x+w//2, y+h2//2), lab, font=hdr_font, anchor="mm", fill="black")
        x += w
    y += h2

    # map rows
    for m in map_list:
        name = m["name"]
        tb   = bans.get(name, {"team_a":{"manual":[],"auto":[]}, "team_b":{"manual":[],"auto":[]}})
        x = 0
        for team_key in ("team_a","team_b"):
            for side in ("Allied","Axis"):
                if final_combo and (name,team_key,side) in final_combo:
                    c = (180,255,180)
                elif side in tb[team_key]["manual"]:
                    c = (255,0,0)
                elif side in tb[team_key]["auto"]:
                    c = (255,165,0)
                else:
                    c = (255,255,255)
                draw.rectangle([x,y,x+sub_w,y+row_h], fill=c, outline="black")
                draw.text((x+sub_w//2, y+row_h//2), side, font=row_font, anchor="mm", fill="black")
                x += sub_w
            # map cell
            draw.rectangle([x,y,x+map_w,y+row_h], fill=(240,240,240), outline="black")
            draw.text((x+map_w//2, y+row_h//2), name, font=row_font, anchor="mm", fill="black")
            x += map_w
        y += row_h

    path = "ban_status.png"
    img.save(path)
    return path

# ─── Message-Editing Helper ────────────────────────────────────────────────────
async def update_status_message(channel_id:int, content:Optional[str], image_path:str):
    channel = bot.get_channel(channel_id)
    if not channel: return
    msg_id = channel_messages.get(channel_id)
    file   = discord.File(image_path)
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(content=content, attachments=[file])
            return
        except discord.NotFound:
            pass
    msg = await channel.send(content=content, file=file)
    channel_messages[channel_id] = msg.id
    save_state()

# ─── Auto-Delete Helper ─────────────────────────────────────────────────────────
async def delete_later(msg:discord.Message, delay:float):
    await asyncio.sleep(delay)
    try: await msg.delete()
    except: pass

# ─── Autocomplete ─────────────────────────────────────────────────────────────
async def map_autocomplete(interaction:discord.Interaction, current:str):
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
    ch = interaction.channel_id
    if ch in ongoing_bans:
        return await interaction.response.send_message(
            "❌ Match already active here. Use `/match_delete` first.", ephemeral=True
        )

    cfg = load_config()
    maps = load_maplist()
    a,b = team_a.name, team_b.name
    ra,rb = cfg["team_regions"].get(a,"Unknown"), cfg["team_regions"].get(b,"Unknown")
    mode = determine_ban_option(ra, rb, cfg)

    # coin flip
    winner = random.choice(["team_a","team_b"])
    channel_flip[ch]     = winner
    channel_mode[ch]     = mode
    channel_decision[ch] = "ban" if mode=="ExtraBan" else None
    first_turn = winner if mode=="ExtraBan" else None

    ongoing_bans[ch]  = {m["name"]:{
                            "team_a":{"manual":[],"auto":[]},
                            "team_b":{"manual":[],"auto":[]}
                        } for m in maps}
    match_turns[ch]   = first_turn
    channel_teams[ch] = (a, b)
    save_state()

    flip_lbl = a if winner=="team_a" else b
    dec_lbl  = "First Ban" if mode=="ExtraBan" else "Waiting"
    cur_lbl  = a if first_turn=="team_a" else (b if first_turn=="team_b" else None)
    img = create_ban_status_image(maps, ongoing_bans[ch], a, b,
                                  mode, flip_lbl, channel_decision[ch], cur_lbl)

    await interaction.response.send_message(
        f"**Match Created**\nTitle: {title}\nTeam A: {a} ({ra})\n"
        f"Team B: {b} ({rb})\nMode: {mode}\n{description}",
        file=discord.File(img)
    )
    msg = await interaction.original_response()
    channel_messages[ch] = msg.id
    save_state()

@app_commands.autocomplete(map_name=map_autocomplete, side=side_autocomplete)
@bot.tree.command(name="ban_map", description="Ban a map side")
async def ban_map(
    interaction:discord.Interaction,
    map_name:str,
    side:str
):
    await interaction.response.defer()
    ch = interaction.channel_id
    if ch not in ongoing_bans:
        return await interaction.followup.send(
            "❌ No match here. Use `/match_create`.", ephemeral=True
        )
    if channel_mode.get(ch)=="DetermineHost" and channel_decision.get(ch) is None:
        return await interaction.followup.send(
            "❌ Waiting for `/match_decide`.", ephemeral=True
        )

    tk = match_turns.get(ch)
    if not tk:
        return await interaction.followup.send(
            "❌ Turn order unset.", ephemeral=True
        )
    role_name = channel_teams[ch][0] if tk=="team_a" else channel_teams[ch][1]
    if role_name not in [r.name for r in interaction.user.roles]:
        return await interaction.followup.send(
            "❌ It’s not your turn.", ephemeral=True
        )

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
            channel_teams[ch][0], channel_teams[ch][1],
            channel_mode[ch],
            channel_teams[ch][0] if channel_flip[ch]=="team_a" else channel_teams[ch][1],
            channel_decision[ch], None
        )
        m,t1,s1 = combos_pre[0]; _,t2,s2 = combos_pre[1]
        tm1 = channel_teams[ch][0] if t1=="team_a" else channel_teams[ch][1]
        tm2 = channel_teams[ch][0] if t2=="team_a" else channel_teams[ch][1]
        content = f"🏁 Ban complete!\n- Map: {m}\n- {tm1} = {s1}\n- {tm2} = {s2}"
        await update_status_message(ch, content, img)
        return await interaction.followup.send(
            "✅ Already complete.", ephemeral=True
        )

    # apply ban
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
    ch = interaction.channel_id
    if ch not in ongoing_bans or channel_flip.get(ch) is None:
        return await interaction.response.send_message("❌ No decision.", ephemeral=True)
    if channel_decision.get(ch) is not None:
        return await interaction.response.send_message("❌ Already decided.", ephemeral=True)
    winner = channel_flip[ch]
    winner_lbl = channel_teams[ch][0] if winner=="team_a" else channel_teams[ch][1]
    if winner_lbl not in [r.name for r in interaction.user.roles]:
        return await interaction.response.send_message("❌ Only flip winner.", ephemeral=True)

    channel_decision[ch] = choice
    match_turns[ch] = winner if choice=="ban" else ("team_b" if winner=="team_a" else "team_a")
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
    await update_status_message(ch,None,img)
    await interaction.response.send_message(
        f"✅ Chose **{'First Ban' if choice=='ban' else 'Host'}**; first ban: **{a_lbl if match_turns[ch]=='team_a' else b_lbl}**.",
        ephemeral=True
    )

@bot.tree.command(name="match_delete", description="Delete the current match")
async def match_delete(interaction:discord.Interaction):
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
