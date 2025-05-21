from datetime import datetime
import discord
from discord import app_commands
from discord.app_commands import Choice
import state
from helpers import (
    format_timestamp,
    remaining_combos,
    update_ban_embed,
    map_autocomplete,
    side_autocomplete,
    flip_turn,
    update_current_turn_embed
)

@app_commands.command(name="ban_map")
@discord.app_commands.checks.cooldown(1, 3.0)
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
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})

    # ─── Determine team_key & check permissions ────────────────────
    turn_idx   = ongoing["current_turn_index"]
    team_roles = ongoing["teams"]  # [role_a_id, role_b_id]
    team_key   = "team_a" if turn_idx % 2 == 0 else "team_b"
    expected  = team_roles[0] if team_key == "team_a" else team_roles[1]
    if expected not in [r.id for r in interaction.user.roles]:
        mention = f"<@&{expected}>"
        return await interaction.response.send_message(
            f"❌ It’s {mention}’s turn, you can’t do that.", ephemeral=True
        )

    # ─── Grab (or init) both ban‐trackers ────────────────────────────
    bans = ongoing.setdefault("bans", [])
    tb   = ongoing.setdefault(
        map_name,
        {"team_a": {"manual": [], "auto": []}, "team_b": {"manual": [], "auto": []}}
    )

    ts = datetime.utcnow().isoformat() + "Z"

    # ─── First ban is a “double” ban, no validation ─────────────────
    if ongoing.get("firstban", True):
        # ─── Subsequent bans must be in remaining_combos ────────────────
        rem = remaining_combos(channel_id)
        if (map_name, side) not in [(m, s) for m, _, s in rem]:
            return await interaction.response.send_message(
                f"❌ Invalid ban: {map_name} {side} isn’t available.", ephemeral=True
            )

        # ─── Record the ban, then flip turn ─────────────────────────────
        bans.append({"map": map_name, "side": side, "timestamp": ts})
        tb[team_key]["manual"].append(side)
        # mirror‐ban the opposite side for the other team
        other_key = "team_b" if team_key == "team_a" else "team_a"
        opp_side   = "Axis" if side == "Allied" else "Allied"
        # record as an auto‐ban on the other side
        if opp_side not in tb[other_key]["auto"]:
            tb[other_key]["auto"].append(opp_side)
        await state.save_state(channel_id)    
        await interaction.response.send_message(
            f"✅ Double ban recorded: **{map_name} {side}** at {format_timestamp(ts)}."
        )

        embed_id = ongoing.get("embed_message_id")
        if embed_id:
            await update_ban_embed(interaction.channel, embed_id,f"Double ban: {map_name} {side} at {format_timestamp(ts)}")
        
        #new_turn = await flip_turn(channel_id)
        #await update_current_turn_embed(interaction.channel, embed_id, new_turn)
        await state.save_state(channel_id)
        return

    # ─── Subsequent bans must be in remaining_combos ────────────────
    rem = remaining_combos(channel_id)
    if (map_name, side) not in [(m, s) for m, _, s in rem]:
        return await interaction.response.send_message(
            f"❌ Invalid ban: {map_name} {side} isn’t available.", ephemeral=True
        )

    # ─── Record the ban, then flip turn ─────────────────────────────
    bans.append({"map": map_name, "side": side, "timestamp": ts})
    tb[team_key]["manual"].append(side)
    # mirror‐ban the opposite side for the other team
    other_key = "team_b" if team_key == "team_a" else "team_a"
    opp_side   = "Axis" if side == "Allied" else "Allied"
    # record as an auto‐ban on the other side
    if opp_side not in tb[other_key]["auto"]:
        tb[other_key]["auto"].append(opp_side)
    await state.save_state(channel_id)    
    await interaction.response.send_message(
        f"✅ Ban recorded: **{map_name} {side}** at {format_timestamp(ts)}."
    )

    embed_id = ongoing.get("embed_message_id")
    if embed_id:
        await update_ban_embed(interaction.channel, embed_id,f"Ban: {map_name} {side} at {format_timestamp(ts)}")
    
    new_turn = await flip_turn(channel_id)
    await update_current_turn_embed(interaction.channel, embed_id, new_turn)
    await state.save_state(channel_id)
        