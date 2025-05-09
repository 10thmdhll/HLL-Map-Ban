from datetime import datetime
import uuid
import os
import json
import discord
from discord import app_commands
import state

@app_commands.command(name="match_create")
@app_commands.describe(
    role_a="Discord role for Team A",
    role_b="Discord role for Team B"
)
async def match_create(
    interaction: discord.Interaction,
    role_a: discord.Role,
    role_b: discord.Role
):
    """Initialize a match, perform a coin flip, and post a status embed."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})

    # Metadata
    ongoing["match_id"] = str(uuid.uuid4())
    ongoing["created_at"] = datetime.utcnow().isoformat() + 'Z'
    ongoing["teams"] = [role_a.id, role_b.id]

    # Coin flip
    chooser = role_a if uuid.uuid4().int % 2 == 0 else role_b
    loser = role_b if chooser == role_a else role_a
    ongoing["coin_flip"] = {
        "winner": chooser.id,
        "loser": loser.id,
        "timestamp": datetime.utcnow().isoformat() + 'Z'
    }

    # Initialize other fields
    ongoing.update({
        "host_or_mode_choice": None,
        "host_role": None,
        "ban_mode": None,
        "bans": [],
        "current_turn_index": 0,
        "scheduled_time": "TBD",
        "casters": {"team_a": None, "team_b": None},
        "additional_casters": [],
        "update_history": [],
        "predictions_poll": None,
        "embed_message_id": None
    })

    await state.save_state(channel_id)

    # Build and send embed
    embed = discord.Embed(title="Match Status", color=discord.Color.blue())
    embed.add_field(name="Teams", value=f"<@&{role_a.id}> vs <@&{role_b.id}>", inline=False)
    embed.add_field(name="Coin Flip Winner", value=f"<@&{chooser.id}>", inline=False)
    embed.add_field(name="Ban Mode", value="TBD", inline=True)
    embed.add_field(name="Host", value="TBD", inline=True)
    embed.add_field(name="Scheduled Time", value=ongoing["scheduled_time"], inline=False)
    embed.add_field(name="Casters", value="TBD", inline=False)

    # Load maps
    TEAMMAP_PATH = os.path.join(os.getcwd(), "teammap.json")
    try:
        with open(TEAMMAP_PATH) as f:
            combos = json.load(f)
        maps = sorted({c[0] for c in combos})
        embed.add_field(name="Available Maps", value=", ".join(maps), inline=False)
    except Exception:
        embed.add_field(name="Available Maps", value="Error loading maps", inline=False)

    msg = await interaction.channel.send(embed=embed)
    ongoing["embed_message_id"] = msg.id
    await state.save_state(channel_id)

    # Acknowledge privately
    await interaction.response.send_message(
        "Match created and status posted.", ephemeral=True
    )