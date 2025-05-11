import datetime
import discord
from discord import app_commands
import state
from helpers import update_ban_mode_choice_embed

@app_commands.command(name="select_ban_mode")
@app_commands.describe(option="Choose ban mode: final or double")
@app_commands.choices(option=[
    app_commands.Choice(name="Final Ban Mode - You pick the final ban but go second.  Other team will pick first twice.", value="final"),
    app_commands.Choice(name="Double Ban Mode - You pick the first two bans.  Other team will pick the final ban.", value="double"),
])
async def select_ban_mode(interaction: discord.Interaction, option: str):
    """Select ban mode or hosting choice after coin flip."""
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
        
    # record the choice in state…
    ongoing["ban_mode"] = {
        "chosen_option": option,
        "chosen_by": interaction.user.id,
        "timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
    }
    ongoing["ban_mode" if option != "host" else "host_role"] = interaction.user.id
    await state.save_state(channel_id)

    # get the message ID of the embed posted in /match_create
    embed_msg_id = ongoing.get("embed_message_id")
    if not embed_msg_id:
        return await interaction.response.send_message(
            "❌ No status embed found to update.", ephemeral=True
        )

    # update only the Host/Mode Choice field on that embed
    await update_ban_mode_choice_embed(
        interaction.channel,
        embed_msg_id,
        option.capitalize()  # or however you want to display it
    )

    # confirm to the user
    await interaction.response.send_message(
        f"✅ Option '{option}' recorded.", ephemeral=True
    )