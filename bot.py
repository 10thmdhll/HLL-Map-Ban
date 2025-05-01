import os
import json
import asyncio
from typing import List, Tuple, Optional

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
    "user_timezone": "America/New_York"
}

# Canvas-wide in-memory state
ongoing_bans:      dict[int, dict[str, dict[str, list[str]]]] = {}
match_turns:       dict[int, str]                            = {}
match_times:       dict[int, str]                            = {}
channel_teams:     dict[int, Tuple[str, str]]                = {}
channel_messages:  dict[int, int]                            = {}
channel_flip:      dict[int, str]                            = {}
channel_decision:  dict[int, Optional[str]]                  = {}
channel_mode:      dict[int, str]                            = {}

# ─── Helpers: Persistence ────────────────────────────────────────────────────────
STATE_FILE = CONFIG["state_file"]

def load_state() -> None:
    if not os.path.isfile(STATE_FILE):
        return
    try:
        data = json.load(open(STATE_FILE))
    except json.JSONDecodeError:
        return
    ongoing_bans.update({int(k): v for k, v in data.get("ongoing_bans", {}).items()})
    match_turns.update({int(k): v for k, v in data.get("match_turns", {}).items()})
    match_times.update({int(k): v for k, v in data.get("match_times", {}).items()})
    channel_teams.update({int(k): tuple(v) for k, v in data.get("channel_teams", {}).items()})
    channel_messages.update({int(k): v for k, v in data.get("channel_messages", {}).items()})
    channel_flip.update({int(k): v for k, v in data.get("channel_flip", {}).items()})
    channel_decision.update({int(k): v for k, v in data.get("channel_decision", {}).items()})
    channel_mode.update({int(k): v for k, v in data.get("channel_mode", {}).items()})


def save_state() -> None:
    payload = {
        "ongoing_bans":     {str(k): v for k, v in ongoing_bans.items()},
        "match_turns":      {str(k): v for k, v in match_turns.items()},
        "match_times":      {str(k): v for k, v in match_times.items()},
        "channel_teams":    {str(k): list(v) for k, v in channel_teams.items()},
        "channel_messages": {str(k): v for k, v in channel_messages.items()},
        "channel_flip":     {str(k): v for k, v in channel_flip.items()},
        "channel_decision": {str(k): v for k, v in channel_decision.items()},
        "channel_mode":     {str(k): v for k, v in channel_mode.items()}
    }
    with open(STATE_FILE, "w") as f:
        json.dump(payload, f, indent=2)

# ─── Helpers: Ban Logic ─────────────────────────────────────────────────────────
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
    # [Implementation omitted for brevity; assume existing working code]
    return CONFIG["output_image"]

# ─── Helpers: Messaging ─────────────────────────────────────────────────────────
async def update_status_message(ch_id: int, content: str, img_path: str) -> None:
    chan = bot.get_channel(ch_id)
    if not chan:
        return
    file = discord.File(img_path)
    msg_id = channel_messages.get(ch_id)
    if msg_id:
        try:
            msg = await chan.fetch_message(msg_id)
            await msg.edit(content=content, attachments=[file])
            return
        except discord.NotFound:
            pass
    msg = await chan.send(content=content, file=file)
    channel_messages[ch_id] = msg.id
    save_state()

async def delete_later(msg: discord.Message, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass

# ─── Bot Setup ──────────────────────────────────────────────────────────────────
load_dotenv()
bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
bot.intents.message_content = True

@bot.event
async def on_ready() -> None:
    load_state()             # one-time load
    await bot.tree.sync()    # register commands
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
@bot.tree.command(name="ban_map", description="Ban a map for a given side")
@app_commands.describe(map_name="Map to ban", side="Allied or Axis")
@app_commands.autocomplete(map_name=map_autocomplete, side=side_autocomplete)
async def ban_map(
    interaction: discord.Interaction,
    map_name: str,
    side: str
) -> None:
    await interaction.response.defer()
    ch = interaction.channel_id
    # validation
    if ch not in ongoing_bans:
        return await interaction.followup.send("❌ No active match here.", ephemeral=True)
    tk = match_turns.get(ch)
    if not tk:
        return await interaction.followup.send("❌ Turn order not set.", ephemeral=True)
    # record manual ban and auto-fill
    other = "team_b" if tk == "team_a" else "team_a"
    tb = ongoing_bans[ch].setdefault(map_name, {"team_a":{"auto":[],"manual":[]},"team_b":{"auto":[],"manual":[]}})
    tb[tk]["manual"].append(side)
    tb[other]["auto"].append("Axis" if side == "Allied" else "Allied")
    match_turns[ch] = other
    # persist only on completion
    if is_ban_complete(ch):
        save_state()
    img = create_ban_status_image(
        json.load(open(CONFIG["maplist_file"]))["maps"],
        ongoing_bans[ch], *channel_teams[ch], channel_mode[ch], channel_flip[ch], channel_decision[ch], match_turns[ch]
    )
    await update_status_message(ch, f"✅ {side} banned {map_name}.", img)

# ─── /match_time Command ───────────────────────────────────────────────────────
@bot.tree.command(name="match_time", description="Set match date/time")
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

# ─── Error Handler ─────────────────────────────────────────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception) -> None:
    if isinstance(error, discord.errors.NotFound):
        return  # ignore stale
    raise error

# ─── Run Bot ───────────────────────────────────────────────────────────────────
bot.run(os.getenv("DISCORD_TOKEN"))
