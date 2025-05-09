import discord
import asyncio
import json
from io import BytesIO
from state import load_state, save_state, ongoing_bans, match_turns, match_times, channel_teams, channel_decision, channel_mode
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from typing import List, Tuple, Optional, Literal, Dict, Union

def remaining_combos(ch: int) -> list[tuple[str, str, str]]:
    """
    Return list of (map, faction_order, side) combinations still available for ban.
    """
    from state import channel_teams, ongoing_bans
    return [
        (m, order, side)
        for m, order, side in channel_teams.get(ch, [])
        if m not in ongoing_bans.get(ch, {})
    ]

def is_ban_complete(ch: int) -> bool:
    combos = remaining_combos(ch)
    return len(combos) == 2 and combos[0][0] == combos[1][0]

async def delete_later(msg: discord.Message, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass
        
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