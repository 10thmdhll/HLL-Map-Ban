import datetime
import discord
from discord import app_commands
import state
from helpers import update_host_mode_choice_embed, flip_turn, update_current_turn_embed, update_ban_mode_choice_embed

@app_commands.command(name="select_host_mode")
@app_commands.describe(option="Choose host option: Final Ban or Host")
@app_commands.choices(option=[
    app_commands.Choice(name="Ban Mode - You pick the Final ban.  Other team will host.", value="Ban"),
    app_commands.Choice(name="Host Match - You pick the Server Location.  Other team will pick the Final ban.", value="Host"),
])
async def select_host_mode(interaction: discord.Interaction, option: str):
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})
    choice_data = ongoing.get("host_role")

    if (choice_data != "TBD"):
        await interaction.response.send_message(f"❌ Host mode is already set.",ephemeral=True,delete_after=15)
        return
    
    # Determine whose turn it is
    turn_idx = ongoing["current_turn_index"] 
    team_roles = ongoing["teams"]
    turn_id = team_roles[turn_idx]
    other_idx = team_roles[0]
    if turn_idx == team_roles[0]:
        other_idx = team_roles[1]
        
    #print(f"turn_idx:{turn_idx}")
    #print(f"other_idx:{other_idx}")

    # Check if the invoking user has that role
    if f"<@&{turn_id}>" not in [r.id for r in interaction.user.roles]:
        await interaction.response.send_message(f"❌ You can’t do that right now.",ephemeral=True,delete_after=15)
        return

    ongoing["host_or_ban_choice"] = {
        "chosen_option": option,
        "chosen_by": interaction.user.id,
        "timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
    }
    # Determine host_role or ban_mode field
    ongoing["ban_mode"] = "Final"
    ongoing["firstban"] = False
    embed_msg_id = ongoing.get("embed_message_id")  
    
    await state.save_state(channel_id)
    
    if option == "Host":
        ongoing["host_role"] = interaction.user.id
        await update_host_mode_choice_embed(interaction.channel,ongoing["embed_message_id"],option) 
        await state.save_state(channel_id)
        new_turn = await flip_turn(channel_id)
        await update_current_turn_embed(interaction.channel, embed_msg_id, new_turn) 
        await update_ban_mode_choice_embed(interaction.channel, embed_msg_id, "Final")
        await state.save_state(channel_id)
    
    else:   
        await update_host_mode_choice_embed(interaction.channel,ongoing["embed_message_id"],option)         
        await update_ban_mode_choice_embed(interaction.channel, embed_msg_id, "Final")
        await state.save_state(channel_id)
    
    await interaction.response.send_message(f"Option '{option}' recorded.",ephemeral=True,delete_after=15)  