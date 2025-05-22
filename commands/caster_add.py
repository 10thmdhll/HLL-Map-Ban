import discord
from discord import app_commands
import state

@app_commands.command(name="caster_add")
async def caster_add(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    await state.load_state(channel_id)