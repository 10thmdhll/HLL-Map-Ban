from datetime import datetime
import uuid
import os
import json
import discord
import pathlib
import logging
from random import choice
from discord import app_commands
import state
from helpers import update_host_mode_choice_embed

logger = logging.getLogger(__name__)

@app_commands.command(name="match_create",description="Create a match between 2 discord roles")
@app_commands.describe(role_a="Discord role for Team A",role_b="Discord role for Team B")
async def match_create(interaction: discord.Interaction,role_a: discord.Role,role_b: discord.Role):
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})
    # Metadata
    ongoing["match_id"] = str(uuid.uuid4())
    ongoing["created_at"] = datetime.utcnow().isoformat() + 'Z'
    ongoing["teams"] = [role_a.id, role_b.id]
    
    # Coin flip
    chooser = choice((role_a, role_b))
    #chooser = role_a if uuid.uuid4().int % 2 == 0 else role_b
    loser = role_b if chooser == role_a else role_a
    ongoing["coin_flip"] = {
        "winner": chooser.id,
        "loser": loser.id,
        "timestamp": datetime.utcnow().isoformat() + 'Z'
    }
    ct = 0
    teams = ongoing["teams"]
    
    if chooser.id == teams[1]:
        ct = 1
    
    ongoing.update({"current_turn_index": ct})
    ongoing.update({"update_history": f"Coinflip winner: <@&{chooser.id}>"})
    # Initialize other fields
    ongoing.update({
        "host_or_ban_choice": None,
        "host_role": None,
        "ban_mode": None,
        "bans": [],
        "scheduled_time": "TBD",
        "casters": None,
        "embed_message_id": None,
        "firstban": True,
        "finalbanpost": False
    })
    await state.save_state(channel_id)
    
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
        
    # ─── Initialize each map’s ban-state 
    for m in maps:
        ongoing.setdefault(
            m,
            {"team_a": {"manual": [], "auto": []},
             "team_b": {"manual": [], "auto": []}}
        )

    # Load regions
    teammap_path = base_dir / "teammap.json"
    region_lookup: dict[str, str] = {}
    host_rules: dict[str, dict[str, str]] = {}
    try:
        with open(teammap_path, "r") as f:
            data = json.load(f)

        # Build role-name → region map from "team_regions"
        for entry in data.get("team_regions", []):
            name = entry["name"]
            region = entry["options"]["region"]
            region_lookup[name] = region

        # Build region_pairings lookup
        for rp in data.get("region_pairings", []):
            src = rp["name"]
            host_rules[src] = rp["options"]

    except Exception as e:
        logger.error("Failed loading teammap.json (%s): %s", teammap_path, e)

    # Map your Discord roles to regions by matching on role.name
    region_a = region_lookup.get(role_a.name, "Unknown")
    region_b = region_lookup.get(role_b.name, "Unknown")
    ongoing["regions"] = {"team_a": region_a, "team_b": region_b}

    # Determine host/ban decision from region_pairings
    decision = "TBD"
    if region_a in host_rules:
        decision = host_rules[region_a].get(region_b, "TBD")
    ongoing["host_or_ban_choice"] = decision
    
    if decision == "Ban":
        ongoing["host_role"] = "Middle Ground Rules"
    else:
        ongoing["host_role"] = "TBD"
        
    # Build and send embed
    embed = discord.Embed(title="Match Status", color=discord.Color.blue())
    embed.add_field(name="Teams",value=f"<@&{role_a.id}> vs <@&{role_b.id}>",inline=True)
    embed.add_field(name="Team Regions",value=f"{role_a.name}: {region_a}\n{role_b.name}: {region_b}",inline=True)
    embed.add_field(name="Coin Flip Winner",value=f"<@&{chooser.id}>",inline=True)
    embed.add_field(name="Host Mode Rules",value=f"{decision}",inline=False)
    embed.add_field(name="Ban Mode", value="TBD", inline=True)
    embed.add_field(name="Host", value=ongoing["host_role"], inline=True)
    embed.add_field(name="Scheduled Time",value=ongoing["scheduled_time"],inline=False)
    embed.add_field(name="Casters", value="TBD", inline=False)
    embed.add_field(name="Update History:", value=ongoing["update_history"],inline=False)
    embed.add_field(name="Current Turn:",value=f"<@&{chooser.id}>",inline=False)
    if decision == "Ban":
        embed.add_field(name="Next Step:",value=f"<@&{chooser.id}>: select_ban_mode" ,inline=False)
    else:
        embed.add_field(name="Next Step:",value=f"<@&{chooser.id}>: select_host_mode" ,inline=False)

    msg = await interaction.channel.send(embed=embed)
    ongoing["embed_message_id"] = msg.id
    await state.save_state(channel_id)

    # Acknowledge privately
    await interaction.response.send_message("Match created and status posted.",ephemeral=True,delete_after=15)
