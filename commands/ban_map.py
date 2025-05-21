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
    update_current_turn_embed,
    send_remaining_maps_embed,
    create_combo_grid_image,
    load_maplist
)

@app_commands.command(name="ban_map")
#@discord.app_commands.checks.cooldown(1, 3.0)
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
    await interaction.response.defer(ephemeral=True)

    # ─── Determine team_key & check permissions ────────────────────
    turn_idx   = ongoing["current_turn_index"]
    team_roles = ongoing["teams"]  # [role_a_id, role_b_id]
    team_key   = "team_a" if turn_idx % 2 == 0 else "team_b"
    expected  = team_roles[0] if team_key == "team_a" else team_roles[1]
    if expected not in [r.id for r in interaction.user.roles]:
        mention = f"<@&{expected}>"
        return await interaction.followup.send(
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
            return await interaction.followup.send(
                f"❌ Invalid ban: {map_name} {side} isn’t available.", ephemeral=True
            )

        # ─── Record the ban
        bans.append({"map": map_name, "side": side, "timestamp": ts})
        tb[team_key]["manual"].append(side)
        # mirror‐ban the opposite side for the other team
        other_key = "team_b" if team_key == "team_a" else "team_a"
        opp_side   = "Axis" if side == "Allied" else "Allied"
        # record as an auto‐ban on the other side
        if opp_side not in tb[other_key]["auto"]:
            tb[other_key]["auto"].append(opp_side)
        await state.save_state(channel_id)    
        await interaction.followup.send(
            f"✅ Double ban recorded: **{map_name} {side}** at {format_timestamp(ts)}.", ephemeral=True
        )

        embed_id = ongoing.get("embed_message_id")
        if embed_id:
            await update_ban_embed(interaction.channel, embed_id,f"Double ban: {map_name} {side} at {format_timestamp(ts)}")
        
        ongoing["firstban"] = False
        #new_turn = await flip_turn(channel_id)
        #await update_current_turn_embed(interaction.channel, embed_id, new_turn)
        ongoing["finalbanpost"] = False
        await state.save_state(channel_id)
        
        return

    # ─── Subsequent bans must be in remaining_combos ────────────────
    rem = remaining_combos(channel_id)
    if (map_name, side) not in [(m, s) for m, _, s in rem]:
        return await interaction.followup.send(
            f"❌ Invalid ban: {map_name} {side} isn’t available.", ephemeral=True
        )
    
    if len(rem) <= 3:
        await interaction.followup.send("🚩 Ban phase complete.", ephemeral=True)
        
        # load the original status embed
        embed_id = ongoing.get("embed_message_id")
        if not embed_id:
            return
        msg = await interaction.channel.fetch_message(embed_id)

        if not msg.embeds:
            raise RuntimeError("No embed found on that message")
        if ongoing["finalbanpost"] == False:
            # 2) Update only the “Next Step” field
            embed = msg.embeds[0]
            idx = next((i for i, f in enumerate(embed.fields)
                        if f.name == "Next Step:"), None)
            label = "Next Step:"
            value = "Set match time and casters"
            
            rmx = next((i for i, f in enumerate(embed.fields)
                        if f.name == "Remaining Maps"), None)
            label2 = "Final Map"
            team_ids     = ongoing["teams"]                 # [role_a_id, role_b_id]
            guild        = interaction.guild
            final_map = rem[0][0]
            sides = { team_key: side for (_map, team_key, side) in rem }
            team_a_name = guild.get_role(team_ids[0]).name
            team_b_name = guild.get_role(team_ids[1]).name
            
            value2 = (f"**{final_map}**  •  "
                f"{team_a_name}: {sides['team_a']}  |  "
                f"{team_b_name}: {sides['team_b']}")
            if idx is None:
                embed.add_field(name=label, value=value, inline=False)
            else:
                embed.set_field_at(idx, name=label, value=value, inline=False)
            if rmx is None:
                embed.add_field(name=label2, value=value2, inline=True)
            else:
                embed.set_field_at(rmx, name=label2, value=value2, inline=True)
            await msg.edit(embed=embed)
        
            # — Post a public winner prediction poll —
            team_ids     = ongoing["teams"]                 # [role_a_id, role_b_id]
            guild        = interaction.guild
            team_a_name  = guild.get_role(team_ids[0]).name
            team_b_name  = guild.get_role(team_ids[1]).name
            poll_channel = interaction.channel
 
            poll = await poll_channel.send(
                "**Winner Predictions**\n"
                "React below to predict the match winner:\n"
                "🇦 for **" + team_a_name + "**\n"
                "🇧 for **" + team_b_name + "**"
)
            await poll.add_reaction("🇦")
            await poll.add_reaction("🇧")
            ongoing["finalbanpost"] = True
            await state.save_state(channel_id)
        else:
            await interaction.followup.send("🚩 Ban phase already completed.", ephemeral=True)
            
        return
        
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
    await interaction.followup.send(f"✅ Ban recorded: **{map_name} {side}** at {format_timestamp(ts)}.", ephemeral=True)

    embed_id = ongoing.get("embed_message_id")
    if embed_id:
        await update_ban_embed(interaction.channel, embed_id,f"Ban: {map_name} {side} at {format_timestamp(ts)}")
    
    new_turn = await flip_turn(channel_id)
    await update_current_turn_embed(interaction.channel, embed_id, new_turn)
    
    role_ids = ongoing["teams"]
    role_a   = interaction.guild.get_role(role_ids[0]).name
    role_b   = interaction.guild.get_role(role_ids[1]).name
    maps = [m["name"] for m in await load_maplist()]
    
    await send_remaining_maps_embed(
        interaction.channel,
        maps,
        ongoing,
        team_names=(role_a, role_b)
    )
    await state.save_state(channel_id)
        