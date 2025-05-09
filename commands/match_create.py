import uuid
import datetime
import os
import json
import discord
from io import BytesIO
from discord import app_commands
from PIL import Image, ImageDraw
import state
from config import HDR_FONT, ROW_FONT

@app_commands.command(name="match_create")
@app_commands.describe(
    role_a="Discord role for Team A",
    role_b="Discord role for Team B"
)
async def match_create(interaction: discord.Interaction, role_a: discord.Role, role_b: discord.Role):
    """Initialize a new match, perform a coin flip, and post status graphic."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    # Initialize match metadata
    match = {
        "match_id": str(uuid.uuid4()),
        "created_at": datetime.datetime.utcnow().isoformat() + 'Z',
        "teams": [role_a.id, role_b.id],
    }
    ongoing = state.ongoing_events.setdefault(channel_id, {})
    ongoing.update(match)
    # Perform coin flip
    chooser = role_a if uuid.uuid4().int % 2 == 0 else role_b
    other = role_b if chooser == role_a else role_a
    ongoing["coin_flip"] = {
        "winner": chooser.id,
        "loser": other.id,
        "timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
    }
    # Default fields
    ongoing["host_or_mode_choice"] = {"chosen_option": None, "timestamp": None}
    ongoing["host_role"] = None
    ongoing["ban_mode"] = None
    ongoing["ban_mode_picker"] = None
    ongoing["bans"] = []
    ongoing["current_turn_index"] = 0
    ongoing["scheduled_time"] = "TBD"
    ongoing["casters"] = {"team_a": None, "team_b": None}
    ongoing["additional_casters"] = []
    ongoing["update_history"] = []
    ongoing["predictions_poll"] = {"message_id": None, "channel_id": None}
    ongoing["embed_message_id"] = None
    # Persist initial state
    await state.save_state(channel_id)

    # Load all map choices from teammap.json
    TEAMMAP_PATH = os.path.join(os.getcwd(), "teammap.json")
    with open(TEAMMAP_PATH) as f:
        combos = json.load(f)
    maps = sorted({entry[0] for entry in combos})

    # Generate status image
    # Layout parameters
    width, header_h = 800, 60
    row_h = 30
    footer_h = 180
    height = header_h + len(maps)*row_h + footer_h
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    # Header
    draw.text((20, 10), "Match Status", font=HDR_FONT, fill="black")
    y = header_h
    # Available maps
    draw.text((20, y), "Available Maps:", font=ROW_FONT, fill="black")
    for m in maps:
        draw.text((200, y), m, font=ROW_FONT, fill="black")
        y += row_h
    # Footer info
    y += 10
    coin = f"Coin-Flip Winner: {chooser.name}"
    draw.text((20, y), coin, font=ROW_FONT, fill="black")
    y += row_h
    draw.text((20, y), "Ban Mode: TBD", font=ROW_FONT, fill="black")
    y += row_h
    host_txt = "Host: TBD"
    draw.text((20, y), host_txt, font=ROW_FONT, fill="black")
    y += row_h
    draw.text((20, y), f"Match Time: {ongoing['scheduled_time']}", font=ROW_FONT, fill="black")
    y += row_h
    draw.text((20, y), "English Caster: TBD", font=ROW_FONT, fill="black")
    y += row_h
    draw.text((20, y), "Additional Casters: TBD", font=ROW_FONT, fill="black")

    # Send image
    with BytesIO() as img_buffer:
        image.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        file = discord.File(fp=img_buffer, filename="match_status.png")
        await interaction.response.send_message(
            "Match initialized and status chart:", file=file
        )
```: discord.Interaction, role_a: discord.Role, role_b: discord.Role):
    """Initialize a new match and perform a coin flip."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    match = {
        "match_id": str(uuid.uuid4()),
        "created_at": datetime.datetime.utcnow().isoformat() + 'Z',
        "teams": [role_a.id, role_b.id],
    }
    ongoing = state.ongoing_events.setdefault(channel_id, {})
    ongoing.update(match)
    # Perform coin flip
    chooser = role_a if uuid.uuid4().int % 2 == 0 else role_b
    other = role_b if chooser == role_a else role_a
    ongoing["coin_flip"] = {
        "winner": chooser.id,
        "loser": other.id,
        "timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
    }
    await state.save_state(channel_id)
    await interaction.response.send_message(
        f"Match created! Coin flip: {chooser.name} won.")