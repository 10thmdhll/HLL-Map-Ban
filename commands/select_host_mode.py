import datetime
import discord
from discord import app_commands
import state
from helpers import update_host_mode_choice_embed, flip_turn, update_current_turn_embed

@app_commands.command(name="select_host_mode")
@app_commands.describe(option="Choose host option: ban or host")
@app_commands.choices(option=[
    app_commands.Choice(name="Ban Mode - You pick the Double or Final ban setting.  Other team will pick host.", value="Ban"),
    app_commands.Choice(name="Host Match - You pick the Server Location.  Other team will pick the Double or Final ban setting.", value="Host"),
])
async def select_host_mode(interaction: discord.Interaction, option: str):
    """Select hosting choice after coin flip."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})
    choice_data = ongoing.get("Host")

    if (choice_data != "TBD"):
        await interaction.response.send_message(f"❌ Host mode is already set.",ephemeral=True)
        return
    
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
    if option == "Host":
        ongoing["host_role"] = interaction.user.id
    
    await update_host_mode_choice_embed(interaction.channel,ongoing["embed_message_id"],option)
    ongoing["Host"] = "Chosen"
        
    embed_msg_id = ongoing.get("embed_message_id")        
    await interaction.response.send_message(f"Option '{option}' recorded.",
                ephemeral=True)
                
    await state.save_state(channel_id)