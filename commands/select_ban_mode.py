import datetime
import discord
from discord import app_commands
import state
from helpers import update_ban_mode_choice_embed, flip_turn, update_current_turn_embed

@app_commands.command(name="select_ban_mode")
@app_commands.describe(option="Choose ban mode: final or double")
@app_commands.choices(option=[
    app_commands.Choice(name="Final Ban Mode - You pick the final ban but go second.  Other team will pick first twice.", value="Final"),
    app_commands.Choice(name="Double Ban Mode - You pick the first two bans.  Other team will pick the final ban.", value="Double"),
])
async def select_ban_mode(interaction: discord.Interaction, option: str):
    """Select ban mode after coin flip."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})
    
    # ─── Prevent re-selection ───────────────────────────────────────────
    choice_data = ongoing.get("ban_mode")
    if (choice_data is not None):
        await interaction.response.send_message(f"❌ Ban mode is already set.",ephemeral=True,delete_after=15)
        return
    # Determine whose turn it is
    turn_idx = ongoing["current_turn_index"]
    team_roles = ongoing["teams"]
    other_idx = team_roles[0]
    if turn_idx == team_roles[0]:
        other_idx = team_roles[1]

    # Check if the invoking user has that role
    if turn_idx not in [r.id for r in interaction.user.roles]:
        role_mention = f"<@&{turn_idx}>"
        await interaction.response.send_message(f"❌ It’s {role_mention}’s turn, you can’t do that right now.",ephemeral=True,delete_after=15)
        return
        
    ongoing["ban_mode"] = {
        "chosen_option": option,
        "chosen_by": interaction.user.id,
        "timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
    }
    
    await update_ban_mode_choice_embed(interaction.channel,ongoing["embed_message_id"],option)
    if option == "Final":
        new_turn = await flip_turn(channel_id)
        embed_msg_id = ongoing.get("embed_message_id")
        await update_current_turn_embed(interaction.channel, embed_msg_id, new_turn)
        await state.save_state(channel_id)
        
    
    await state.save_state(channel_id)
    await interaction.response.send_message(f"✅ Option '{option}' recorded.", ephemeral=True,delete_after=15)