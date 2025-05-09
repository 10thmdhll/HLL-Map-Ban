from datetime import datetime
import uuid
import os
import json
import discord
import pathlib
import logging
from discord import app_commands
import state

logger = logging.getLogger(__name__)

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
    embed.add_field(
        name="Teams",
        value=f"<@&{role_a.id}> vs <@&{role_b.id}>",
        inline=False
    )
    embed.add_field(
        name="Coin Flip Winner",
        value=f"<@&{chooser.id}>",
        inline=False
    )
    embed.add_field(name="Ban Mode", value="TBD", inline=True)
    embed.add_field(name="Host", value="TBD", inline=True)
    embed.add_field(
        name="Scheduled Time",
        value=ongoing["scheduled_time"],
        inline=False
    )
    embed.add_field(name="Casters", value="TBD", inline=False)

    # Load maps
    base_dir = pathlib.Path(__file__).parent.parent
    maplist_path = base_dir / "maplist.json"
    
    maps = []
    try:
        with open(maplist_path, 'r') as f:
            data = json.load(f)
        
        if isinstance(data, dict) and "maps" in data:
            maps = [entry["name"] for entry in data["maps"]]
        elif isinstance(data, list):
            maps = sorted({c[0] for c in data})
        else:
            raise ValueError(f"Unexpected maplist format: {type(data)}")
    except Exception as e:
        logger.error("Failed loading maps from %s: %s", maplist_path, e)

    # ─── Load and assign regions to each team ────────────────────────────────
    teamlist_path = base_dir / "teammap.json"
    region_lookup: dict[int, str] = {}
    try:
        with open(teamlist_path, "r") as f:
            data = json.load(f)

        # Expecting { "team_regions": [ { "role_id": 123, "region": "NA" }, … ] }
        if not (isinstance(data, dict) and "team_regions" in data):
            raise ValueError(f"Unexpected teammap format: {type(data)}")

        for entry in data["team_regions"]:
            rid = int(entry["role_id"])
            region_lookup[rid] = entry["region"]

    except Exception as e:
        logger.error("Failed loading team regions from %s: %s", teamlist_path, e)

    # pull each team’s region, default to "Unknown"
    region_a = region_lookup.get(role_a.id, "Unknown")
    region_b = region_lookup.get(role_b.id, "Unknown")
    ongoing["regions"] = {"team_a": region_a, "team_b": region_b}

    # compare for cross‐region or same‐region
    if region_a == "Unknown" or region_b == "Unknown":
        region_comparison = "Unknown team mapping."
    elif region_a == region_b:
        region_comparison = "Same Region"
    else:
        region_comparison = "Cross-Region"

    embed.add_field(name="Team Regions",
                    value=f"Team A: {region_a}\nTeam B: {region_b}",
                    inline=False)
    embed.add_field(name="Region Comparison",
                    value=region_comparison,
                    inline=False)
    
    embed.add_field(
        name="Current step status:",
        value="Match Created" ,
        inline=False
    )

    msg = await interaction.channel.send(embed=embed)
    ongoing["embed_message_id"] = msg.id
    await state.save_state(channel_id)

    # Acknowledge privately
    await interaction.response.send_message(
        "Match created and status posted.",
        ephemeral=True
    )
