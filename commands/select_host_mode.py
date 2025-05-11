import datetime
import discord
from discord import app_commands
import state
from helpers import update_host_mode_choice_embed

@app_commands.command(name="select_host_mode")
@app_commands.describe(option="Choose host option: ban or host")
@app_commands.choices(option=[
    app_commands.Choice(name="Ban Mode - You pick the Double or Final ban setting.  Other team will pick host.", value="ban"),
    app_commands.Choice(name="Host Match - You pick the Server Location.  Other team will pick the Double or Final ban setting.", value="host"),
])
async def select_host_mode(interaction: discord.Interaction, option: str):
    """Select ban mode or hosting choice after coin flip."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    
    # ─── Prevent re-selection ───────────────────────────────────────────
    prev = ongoing.get("host_or_mode_choice", {}).get("chosen_option")
    if prev:
        return await interaction.response.send_message(
            f"❌ Host/Ban mode is already set to **{prev}**.",
            ephemeral=True
        )
    
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

    ongoing["host_or_mode_choice"] = {
        "chosen_option": option,
        "chosen_by": interaction.user.id,
        "timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
    }
    # Determine host_role or ban_mode field
    if option == "host":
        ongoing["host_role"] = interaction.user.id
    else:
        ongoing["ban_mode"] = option
        ongoing["ban_mode_picker"] = interaction.user.id
    await state.save_state(channel_id)
        
    msg = await interaction.channel.send(embed=embed)
    ongoing["embed_message_id"] = msg.id
    await state.save_state(channel_id)
    await update_host_mode_choice_embed(interaction.channel,ongoing["embed_message_id"],option)
    await interaction.response.send_message(f"Option '{option}' recorded.")