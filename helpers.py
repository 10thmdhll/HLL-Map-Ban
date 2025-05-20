from datetime import datetime
from typing import List, Tuple, Optional
import state
import discord
from io import BytesIO
import config
from PIL import Image, ImageDraw, ImageFont
from discord import TextChannel, app_commands

def format_timestamp(ts: str) -> str:
    from datetime import datetime
    dt = datetime.fromisoformat(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    
def remaining_combos(ch: int) -> List[Tuple[str, str, str]]:
    """
    Return list of (map, team_key, side) combinations still available for ban.
    Assumes ongoing_events[ch] stores a dict of maps to {'team_a': {'manual':[], 'auto':[]}, 'team_b': {...}}.
    """
    combos: List[Tuple[str, str, str]] = []
    channel_data = ongoing_events.get(ch, {})
    for m, tb in channel_data.items():
        for team_key in ("team_a", "team_b"):
            team_data = tb.get(team_key, {})
            manual = team_data.get("manual", [])
            auto = team_data.get("auto", [])
            for side in ("Allied", "Axis"):
                if side not in manual and side not in auto:
                    combos.append((m, team_key, side))
    return combos
    
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
    current_mention = f"<@&{ct_role.id}>"
    other_mention = (
        role_mentions[1]
        if role_mentions[0] == current_mention
        else role_mentions[0]
)
    other_role_id = int(other_mention.strip("<@&>"))
    other_role = interaction.guild.get_role(other_role_id)
    
    if new_choice == "host":
        new_host = ct_role
    if new_choice == "ban":
        new_host = other_role
            
    if field_index is None:
        # If it doesn’t exist yet, append it instead
        embed.add_field(name="Host", value=new_host, inline=False)
    else:
        # 4) Mutate that field in-place
        embed.set_field_at(field_index, name="Host", value=new_host, inline=True)
        
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
        new_val2 = "Current turn role: map_ban"
        embed.set_field_at(next_step_index,name="Next Step:",value=new_val2,inline=False)

    # 5) Push the edit back to Discord
    await msg.edit(embed=embed)
    
async def flip_turn(channel_id: int) -> int:
    """
    Advance the current_turn_index to the next team (wraps around),
    save state, and return the new turn index.
    """
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
     
    history_index = next(
        (i for i, f in enumerate(embed.fields) if f.name == "Update History:"), None)
            
    if history_index is None:
        embed.add_field(name="Update History:",value=f"{ct_role} choice: {new_choice}",inline=False)
    else:
        prev = embed.fields[history_index].value or ""    
        new_val = prev + "\n" + f"{ct_role} choice: {new_choice}"
        embed.set_field_at(history_index,name="Update History:",value=new_val,inline=False)
     
    if next_step_index is None:
        embed.add_field(name="Next Step:",value=f"{ct_role} choice: {new_choice}",inline=False)
    else:
        new_val2 = "Current turn role: map_ban"
        embed.set_field_at(next_step_index,name="Next Step:",value=new_val2,inline=False)

    # 5) Push the edit back to Discord
    await msg.edit(embed=embed)

def create_ban_status_image(maps,bans) -> Image:
    # — Derive display names —
    A = team_a_name or "Team A"
    B = team_b_name or "Team B"
    
    current = A if current_turn == "team_a" else B if current_turn == "team_b" else "TBD"
    decision = decision_choice or "None"
    banner1 = f"Current Turn: {current}"
    
    padding = 20
    line_spacer = 10
    
    # — Measure banner heights —
    dummy = Image.new("RGB", (1,1))
    measure = ImageDraw.Draw(dummy)
    bbox1 = measure.textbbox((0, 0), banner1, font=hdr_font)
    h1 = bbox1[3] - bbox1[1]

    header_h = padding + h1 + line_spacer

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
    
def create_ban_image_bytes(
    maps, bans
) -> BytesIO:
    # 1) Build your PIL Image exactly as before, but don’t save it to a file:
    img = create_ban_status_image(maps, bans)

    # 2) Dump it into a BytesIO buffer
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

async def load_teammap() -> dict:
    with open(CONFIG["teammap_file"]) as f:
        return json.load(f)

async def load_maplist() -> List[dict]:
    with open(CONFIG["maplist_file"]) as f:
        return json.load(f)["maps"]
        
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
        tb = ongoing.get(ch, {}).get(name)
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
    tb = ongoing[ch].get(sel_map, {})
    team_key = match_turns.get(ch)
    if not tb or not team_key:
        return []
    choices: List[app_commands.Choice[str]] = []
    for side in ("Allied", "Axis"):
        if side not in tb[team_key]["manual"] and side not in tb[team_key]["auto"]:
            if current.lower() in side.lower():
                choices.append(app_commands.Choice(name=side, value=side))
    return choices[:50]