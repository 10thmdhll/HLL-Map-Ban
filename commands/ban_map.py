from datetime import datetime
import discord
from discord import app_commands
from discord.app_commands import Choice
import state
from helpers import format_timestamp, remaining_combos, update_ban_embed, create_ban_image_bytes, map_autocomplete, side_autocomplete

@app_commands.command(name="ban_map")
@app_commands.describe(
    map_name="Map to ban",
    side="Team side identifier"
)
@app_commands.autocomplete(
    map_name=map_autocomplete,
    side=side_autocomplete
)
async def ban_map(
    interaction: discord.Interaction,
    map_name: str,
    side: str
):
    """Record a map ban and update turn index based on remaining combos."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})

    # Determine whose turn it is
    turn_idx = ongoing["current_turn_index"]
    team_roles = ongoing["teams"]  # [role_a_id, role_b_id]
    # even turns → team A, odd turns → team B
    expected_role_id = team_roles[0] if turn_idx % 2 == 0 else team_roles[1]

    # Check if the invoking user has that role
    if expected_role_id not in [r.id for r in interaction.user.roles]:
        role_mention = f"<@&{expected_role_id}>"
        return await interaction.response.send_message(
            f"❌ It’s {role_mention}’s turn, you can’t do that right now.",
            ephemeral=True
        )

    # First Ban gets double
    if (ongoing["firstban"] == True):
        bans = ongoing.setdefault("bans", [])
        ts = datetime.utcnow().isoformat() + 'Z'
        bans.append({"map": map_name, "side": side, "timestamp": ts})
        
        tb = ongoing.setdefault(map_name, {"team_a": {"manual": [], "auto": []}, "team_b": {"manual": [], "auto": []}})
        
        await state.save_state(channel_id)
        await interaction.response.send_message(
        f"Banned {map_name} - {side} at {format_timestamp(ts)} as double ban option.")
        
        # get the message ID of the embed posted in /match_create
        embed_msg_id = ongoing.get("embed_message_id")
        if not embed_msg_id:
            return await interaction.response.send_message(
                "❌ No status embed found to update.", ephemeral=True
            )
        
        await update_ban_embed(
            interaction.channel,
            embed_msg_id,
            f"Banned {map_name} - {side} at {format_timestamp(ts)} as double ban option."
        )
        
        ongoing["firstban"] = False
        await state.save_state(channel_id)
        return
    
    # Determine remaining combos
    rem = remaining_combos(channel_id)
    # Validate chosen combo is available
    if (map_name, side) not in [(m, s) for m, _, s in rem]:
        return await interaction.response.send_message(
            f"❌ Invalid ban: {map_name} ({side}) is not available.", ephemeral=True
        )
        
    # Record ban
    ts = datetime.utcnow().isoformat() + 'Z'
    bans = ongoing["bans"]
    bans.append({"map": map_name, "side": side, "timestamp": ts})
    ongoing["current_turn_index"] = len(bans) - 1

    # Track manual bans per team
    tb = ongoing.setdefault(map_name, {"team_a": {"manual": [], "auto": []}, "team_b": {"manual": [], "auto": []}})
    # Determine which team_key
    # Assuming side maps uniquely to team_key context; here we store under both teams for example
    if "team_a" in ongoing.get("teams", []):
        tb_key = "team_a"
    else:
        tb_key = "team_b"
    tb[tb_key]["manual"].append(side)

    await state.save_state(channel_id)
    await interaction.response.send_message(
        f"Banned {map_name} - {side} at {format_timestamp(ts)}.")
    
    await update_ban_embed(interaction.channel,embed_msg_id,
            f"Banned {map_name} - {side} at {format_timestamp(ts)} as ban option."
        )
    
    new_turn = await flip_turn(channel_id)
    await state.save_state(channel_id)
    embed_msg_id = ongoing.get("embed_message_id")
    await update_current_turn_embed(interaction.channel, embed_msg_id, new_turn)