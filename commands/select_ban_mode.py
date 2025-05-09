import datetime
import discord
from discord import app_commands
import state

@app_commands.command(name="select_ban_mode")
@app_commands.describe(option="Choose ban mode: final or double")
async def select_ban_mode(interaction: discord.Interaction, option: str):
    """Select ban mode or hosting choice after coin flip."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})
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
    await interaction.response.send_message(f"Option '{option}' recorded.")