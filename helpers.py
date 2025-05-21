from datetime import datetime, timezone
from typing import List, Tuple, Optional, Dict
import state
import discord
from discord import app_commands, TextChannel
from discord.app_commands import Choice
from io import BytesIO
import config
import json
import uuid
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def format_timestamp(ts: str) -> str:
    from datetime import datetime
    dt = datetime.fromisoformat(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    
def remaining_combos(ch: int) -> List[Tuple[str, str, str]]:
    combos: List[Tuple[str, str, str]] = []
    channel_data = state.ongoing_events.get(ch, {})

    for m, tb in channel_data.items():
        # Skip anything that isn't a map-like dict
        if not isinstance(tb, dict):
            continue
        team_a = tb.get("team_a")
        team_b = tb.get("team_b")
        if not (isinstance(team_a, dict) and isinstance(team_b, dict)):
            continue

        for team_key in ("team_a", "team_b"):
            team_data = tb[team_key]
            manual = team_data.get("manual", [])
            auto   = team_data.get("auto", [])
            for side in ("Allied", "Axis"):
                if side not in manual and side not in auto:
                    combos.append((m, team_key, side))

    return combos
    
def chunk_history_lines(lines: List[str], max_chars: int = 1024) -> List[str]:
    chunks: List[str] = []
    current = ""
    for line in lines:
        # +1 for the newline
        if current and len(current) + len(line) + 1 > max_chars:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks
    
async def update_host_mode_choice_embed(channel: discord.TextChannel, message_id: int, new_choice: str):
    # 1) Fetch the bot’s original embed message
    msg = await channel.fetch_message(message_id)
    if not msg.embeds:
        raise RuntimeError("No embed found on that message")

    # 2) Clone the existing embed
    embed = msg.embeds[0]
    
    # 3) Find the index of the field you want to update
    ct_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Current Turn:"), None)
    
    ct_role = embed.fields[ct_index].value
        
    field_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Host"), None)
    
    history_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Update History:"), None)
    
    next_step_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Next Step:"), None) 
    
    tm_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Teams"), None)
    
    teams_val = embed.fields[tm_index].value
    role_mentions = [part.strip() for part in teams_val.split(" vs ")]
    current_mention = ct_role
    other_mention = (
        role_mentions[1]
        if role_mentions[0] == current_mention
        else role_mentions[0]
        )
    
    if new_choice == "Host":
        new_host = ct_role
    if new_choice == "Ban":
        new_host = other_mention
            
    if field_index is None:
        # If it doesn’t exist yet, append it instead
        embed.add_field(name="Host", value=f"{new_host}", inline=False)
    else:
        # 4) Mutate that field in-place
        embed.set_field_at(field_index, name="Host", value=f"{new_host}", inline=True)
        
    if history_index is None:
        embed.add_field(name="Update History:",value=f"{ct_role} choice: {new_choice}",inline=False)
    else:
        prev = embed.fields[history_index].value or ""    
        new_val = prev + "\n" + f"{ct_role} choice: {new_choice}"
        embed.set_field_at(history_index,name="Update History:",value=new_val,inline=False)
     
    if next_step_index is None:
        embed.add_field(name="Next Step:",value=f"{ct_role} choice: {new_choice}",inline=False)
    else:
        new_val2 = "Current turn role: select_ban_mode"
        embed.set_field_at(next_step_index,name="Next Step:",value=new_val2,inline=False)

    # 5) Push the edit back to Discord
    await msg.edit(embed=embed)
    
    if new_choice == "Host":
        msg = await channel.fetch_message(message_id)
        new_turn = await flip_turn(channel.id)
        await update_current_turn_embed(channel, message_id, new_turn)
    
async def update_ban_mode_choice_embed(channel: discord.TextChannel, message_id: int, new_choice: str):
    # 1) Fetch the bot’s original embed message
    msg = await channel.fetch_message(message_id)
    if not msg.embeds:
        raise RuntimeError("No embed found on that message")

    # 2) Clone the existing embed
    embed = msg.embeds[0]
    
    ct_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Current Turn:"), None)
 
    ct_role = embed.fields[ct_index].value
    
    field_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Ban Mode"), None)
    
    history_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Update History:"), None)
    
    next_step_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Next Step:"), None) 
    
    if field_index is None:
        # If it doesn’t exist yet, append it instead
        embed.add_field(name="Ban Mode", value=new_choice, inline=False)
    else:
        # 4) Mutate that field in-place
        embed.set_field_at(field_index, name="Ban Mode", value=new_choice, inline=True)
        
    if history_index is None:
        embed.add_field(name="Update History:",value=f"{ct_role} choice: {new_choice}",inline=False)
    else:
        prev = embed.fields[history_index].value or ""    
        new_val = prev + "\n" + f"{ct_role} choice: {new_choice}"
        embed.set_field_at(history_index,name="Update History:",value=new_val,inline=False)
     
    if next_step_index is None:
        embed.add_field(name="Next Step:",value=f"{ct_role} choice: {new_choice}",inline=False)
    else:
        new_val2 = "Current turn role: ban_map"
        embed.set_field_at(next_step_index,name="Next Step:",value=new_val2,inline=False)

    # 5) Push the edit back to Discord
    await msg.edit(embed=embed)
    
async def update_mt_embed(channel: discord.TextChannel, message_id: int, time: str):
    # 1) Fetch the bot’s original embed message
    msg = await channel.fetch_message(message_id)
    if not msg.embeds:
        raise RuntimeError("No embed found on that message")

    # 2) Clone the existing embed
    embed = msg.embeds[0]
    
    field_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Scheduled Time"), None)
    
    next_step_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Next Step:"), None)
    
    # Convert your stored ISO string to a Unix timestamp
    dt = datetime.fromisoformat(time)
    dt_utc   = dt.astimezone(timezone.utc)
    unix_sec = int(dt_utc.timestamp())

    # Build the Discord‐timestamp markup
    ts_field = f"<t:{unix_sec}:F>"
    
    if field_index is None:
        # If it doesn’t exist yet, append it instead
        embed.add_field(name="Scheduled Time", value=ts_field, inline=False)
    else:
        # 4) Mutate that field in-place
        embed.set_field_at(field_index, name="Scheduled Time", value=ts_field, inline=True)
     
    if next_step_index is None:
        embed.add_field(name="Next Step:",value=f"Current turn role: Add Casters",inline=False)
    else:
        new_val2 = "Current turn role: Add Casters"
        embed.set_field_at(next_step_index,name="Next Step:",value=new_val2,inline=False)

    # 5) Push the edit back to Discord
    await msg.edit(embed=embed)
    
async def flip_turn(channel_id: int) -> int:
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})

    teams = ongoing.get("teams", [])
    if len(teams) < 2:
        raise RuntimeError("Cannot flip turn: 'teams' is not set or has fewer than 2 entries")

    current = ongoing.get("current_turn_index", 0)
    new_turn = (current + 1) % len(teams)
    ongoing["current_turn_index"] = new_turn

    # ─── Safely append to update_history ─────────────────────────────────
    history = ongoing.get("update_history")
    if not isinstance(history, list):
        history = []
    history.append({
        "event": "turn_flipped",
        "new_turn_index": new_turn,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })
    ongoing["update_history"] = history

    await state.save_state(channel_id)
    return new_turn
    
async def update_current_turn_embed(
    channel: discord.TextChannel,
    message_id: int,
    new_turn_index: int
) -> None:
    """
    Fetch the existing status embed by message_id, find the 'Current Turn' field,
    and update it to point to the correct team role mention.
    """
    # Load the latest state to resolve which role ID corresponds to this turn
    await state.load_state(channel.id)
    ongoing = state.ongoing_events[channel.id]
    teams = ongoing.get("teams", [])
    if new_turn_index >= len(teams):
        return  # sanity check

    next_role_id = teams[new_turn_index]

    # Fetch and edit the embed
    msg = await channel.fetch_message(message_id)
    if not msg.embeds:
        raise RuntimeError("No embed found on that message")

    embed = msg.embeds[0]
    # Find or append the 'Current Turn' field
    idx = next((i for i,f in enumerate(embed.fields) if f.name == "Current Turn:"), None)
    mention = f"<@&{next_role_id}>"
    if idx is None:
        embed.add_field(name="Current Turn:", value=mention, inline=False)
    else:
        embed.set_field_at(idx, name="Current Turn:", value=mention, inline=False)

    await msg.edit(embed=embed)
    
async def update_ban_embed(channel: discord.TextChannel, message_id: int, new_choice: str):
    # 1) Fetch the bot’s original embed message
    msg = await channel.fetch_message(message_id)
    if not msg.embeds:
        raise RuntimeError("No embed found on that message")

    # 2) Clone the existing embed
    embed = msg.embeds[0]
    
    ct_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Current Turn:"), None)
 
    ct_role = embed.fields[ct_index].value
    
    next_step_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Next Step:"), None) 
    
    tm_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Teams"), None)
    
    history_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Update History:"), None)
     
    if next_step_index is None:
        embed.add_field(name="Next Step:",value=f"{ct_role} choice: {new_choice}",inline=False)
    else:
        new_val2 = "Current turn role: map_ban"
        embed.set_field_at(next_step_index,name="Next Step:",value=new_val2,inline=False)

    # find all existing history fields
    history_indices = [
        i for i, f in enumerate(embed.fields)
        if f.name.startswith("Update History")
    ]

    # pull old lines
    old_lines: List[str] = []
    for idx in history_indices:
        old_lines.extend(embed.fields[idx].value.split("\n"))

    # append the new line
    new_line = f"{ct_role} choice: {new_choice}"
    old_lines.append(new_line)

    # chunk into ≤1024-char blocks
    chunks = chunk_history_lines(old_lines)

    # remove ALL old history fields (from back to front)
    for idx in reversed(history_indices):
        embed.remove_field(idx)

    # insert new chunked history fields
    for i, chunk in enumerate(chunks, start=1):
        name = "Update History" if i == 1 else f"Update History ({i})"
        embed.add_field(name=name, value=chunk, inline=False)

    # 5) Push the edit back to Discord
    await msg.edit(embed=embed)

async def load_teammap() -> dict:
    with open("teammap.json") as f:
        return json.load(f)

MAPLIST_FILE = Path(__file__).parent / "maplist.json"
async def load_maplist() -> list[dict]:
    with open(MAPLIST_FILE) as f:
        return json.load(f)["maps"]


async def map_autocomplete(interaction, current: str) -> list[Choice[str]]:
    combos = remaining_combos(interaction.channel.id)
    if combos:
        maps = sorted({m for m, _, _ in combos})
    else:
        # first‐ban fallback: offer every map
        maps = [m["name"] for m in await load_maplist()]

    return [
        Choice(name=m, value=m)
        for m in maps
        if current.lower() in m.lower()
    ][:25]


async def side_autocomplete(interaction, current: str) -> List[Choice[str]]:
    ch      = interaction.channel.id
    sel_map = getattr(interaction.namespace, "map_name", None)
    if not sel_map:
        return []

    # figure out whose turn
    state_data   = state.ongoing_events.get(ch, {})
    turn_idx     = state_data.get("current_turn_index", 0)
    team_key     = "team_a" if turn_idx % 2 == 0 else "team_b"

    # only look at that team's slots for this map
    tb           = state_data.get(sel_map, {})
    team_data    = tb.get(team_key, {"manual": [], "auto": []})
    manual       = team_data.get("manual", [])
    auto         = team_data.get("auto", [])

    # any side not in either list is still open
    open_sides   = [s for s in ("Allied", "Axis") if s not in manual and s not in auto]

    # if somehow you have neither banning list yet, offer both
    if not open_sides:
        open_sides = ["Allied", "Axis"]

    return [
        Choice(name=s, value=s)
        for s in open_sides
        if current.lower() in s.lower()
    ][:25]
    
def create_combo_grid_image(
    maps: List[str],
    state_data: Dict[str, Dict[str, Dict[str, List[str]]]],
    team_names: Tuple[str, str] = ("Team A", "Team B")
) -> Image.Image:
    """
    Build a grid image showing combos for each map and team, coloring cells:
      • manual bans → Red (#ff0000)
      • auto   bans → Orange (#ffa500)
      • otherwise → White (#ffffff)
    """
    team_keys = ["team_a", "team_b"]
    sides     = ["Allied", "Axis"]
    cell_w    = 75
    map_w     = 150
    cell_h    = 20
    header_h  = 20
    group_h   = 20
    margin    = 5

    width  = margin*2 + cell_w*2 + map_w + cell_w*2
    height = margin*2 + group_h + header_h + len(maps)*cell_h

    img  = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    def text_size(txt: str):
        bbox = draw.textbbox((0,0), txt, font=font)
        return bbox[2]-bbox[0], bbox[3]-bbox[1]

    # ─── Group header ─────────────────────────────────────────────
    x = margin
    for idx, team in enumerate(team_names):
        span_w = cell_w*2
        draw.rectangle([x, margin, x+span_w, margin+group_h],
                       fill="#cccccc", outline="black")
        w, h = text_size(team)
        draw.text((x + (span_w-w)/2, margin + (group_h-h)/2),
                  team, fill="black", font=font)
        x += span_w + (map_w if idx == 0 else 0)

    # “Maps” group header
    draw.rectangle(
        [margin + cell_w*2, margin,
         margin + cell_w*2 + map_w, margin + group_h],
        fill="#cccccc", outline="black"
    )
    w, h = text_size("Maps")
    draw.text(
        (margin + cell_w*2 + (map_w-w)/2,
         margin + (group_h-h)/2),
        "Maps", fill="black", font=font
    )

    # ─── Sub-headers (Allied/Axis/Maps) ────────────────────────────
    y0 = margin + group_h
    x  = margin
    for _ in team_keys:
        for side in sides:
            draw.rectangle([x, y0, x+cell_w, y0+header_h],
                           fill="#e0e0e0", outline="black")
            w, h = text_size(side)
            draw.text((x + (cell_w-w)/2, y0 + (header_h-h)/2),
                      side, fill="black", font=font)
            x += cell_w
        x += map_w
    # Maps sub-header
    draw.rectangle(
        [margin + cell_w*2, y0,
         margin + cell_w*2 + map_w, y0 + header_h],
        fill="#e0e0e0", outline="black"
    )
    w, h = text_size("Maps")
    draw.text(
        (margin + cell_w*2 + (map_w-w)/2,
         y0 + (header_h-h)/2),
        "Maps", fill="black", font=font
    )

    # ─── Rows ──────────────────────────────────────────────────────
    for i, m in enumerate(maps):
        y = margin + group_h + header_h + i*cell_h
        x = margin

        tb_a = state_data.get(m, {}).get("team_a", {"manual": [], "auto": []})
        tb_b = state_data.get(m, {}).get("team_b", {"manual": [], "auto": []})
        manual_a, auto_a = tb_a["manual"], tb_a["auto"]
        manual_b, auto_b = tb_b["manual"], tb_b["auto"]

        # Team A cells
        for side in sides:
            if side in manual_a:
                fill = "#ff0000"
            elif side in auto_a:
                fill = "#ffa500"
            else:
                fill = "#ffffff"
            draw.rectangle([x, y, x+cell_w, y+cell_h],
                           fill=fill, outline="black")
            w, h = text_size(side)
            draw.text((x + (cell_w-w)/2, y + (cell_h-h)/2),
                      side, fill="black", font=font)
            x += cell_w

        # Map name cell
        draw.rectangle([x, y, x+map_w, y+cell_h],
                       fill="#dddddd", outline="black")
        w, h = text_size(m)
        draw.text((x + (map_w-w)/2, y + (cell_h-h)/2),
                  m, fill="black", font=font)
        x += map_w

        # Team B cells
        for side in sides:
            if side in manual_b:
                fill = "#ff0000"
            elif side in auto_b:
                fill = "#ffa500"
            else:
                fill = "#ffffff"
            draw.rectangle([x, y, x+cell_w, y+cell_h],
                           fill=fill, outline="black")
            w, h = text_size(side)
            draw.text((x + (cell_w-w)/2, y + (cell_h-h)/2),
                      side, fill="black", font=font)
            x += cell_w

    return img

async def send_remaining_maps_embed(
    channel: discord.TextChannel,
    maps: list[str],
    state_data: dict,
    team_names: tuple[str, str] = ("Team A", "Team B")
):
    embed_id    = state_data["embed_message_id"]
    status_msg = None
    
    # 1) Try to fetch the existing embed
    if embed_id:
        try:
            status_msg = await channel.fetch_message(embed_id)
        except discord.NotFound:
            # it was deleted: clear out the old reference so we know to rebuild
            state_data.pop("embed_message_id", None)
            await state.save_state(channel.id)
            
    # 2) If we don't have a status_msg, rebuild & send it
    if status_msg is None:
        # Reconstruct the embed from state_data
        embed = discord.Embed(title="Match Status", color=discord.Color.blue())
        # (fill in all your fields from state_data here, exactly like in match_create)
        teams = state_data["teams"]
        embed.add_field(
            name="Teams",
            value=f"<@&{teams[0]}> vs <@&{teams[1]}>",
            inline=True
        )
        # … add Scheduled Time, Coin Flip, Host, etc. …
        status_msg = await channel.send(embed=embed)
        state_data["embed_message_id"] = status_msg.id
        await state.save_state(channel.id)
            
    grid_msg_id = state_data.get("grid_msg_id")

    # ─── Delete the old grid message ───────────────────────────────
    if grid_msg_id:
        try:
            old = await channel.fetch_message(grid_msg_id)
            await old.delete()
        except discord.NotFound:
            pass

    # ─── Build fresh PIL image ─────────────────────────────────────
    img = create_combo_grid_image(maps, state_data, team_names)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    # ─── Prepare Discord file & update main embed ─────────────────
    filename = f"remaining_maps_{uuid.uuid4().hex}.png"
    file     = discord.File(buf, filename=filename)

    status_msg = await channel.fetch_message(embed_id)
    embed      = status_msg.embeds[0]

    # ensure the “Remaining Maps” field exists (or update it)
    idx = next((i for i,f in enumerate(embed.fields)
                if f.name == "Remaining Maps"), None)
    if idx is None:
        embed.add_field(name="Remaining Maps", value="See chart below", inline=False)
    else:
        embed.set_field_at(idx, name="Remaining Maps", value="See chart below", inline=False)

    # point the embed’s image at our new attachment
    embed.set_image(url=f"attachment://{filename}")

    # ─── Finally send one new grid message ─────────────────────────
    grid_msg = await channel.send(embed=embed, file=file)

    # ─── Persist its ID so next time we delete & replace ───────────
    state_data["grid_msg_id"] = grid_msg.id
    await state.save_state(channel.id)