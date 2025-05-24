from typing import Optional
import discord
from discord import app_commands
import state
from helpers import update_casters_embed

@app_commands.command(name="caster_add",description="Add a link to the match")
@app_commands.describe(member="Which link you want to add as a caster")
async def caster_add(interaction: discord.Interaction,member: str):
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})
    casters = ongoing.get("casters")
    if casters is None:
        casters = []
        ongoing["casters"] = casters
        
    if member in casters:
        return await interaction.response.send_message(f"❌ {member} is already in the casters list.",ephemeral=True,delete_after=15)

    casters.append(member.id)
    await state.save_state(channel_id)

    await interaction.response.send_message(f"✅ Added {member.mention} to casters.",ephemeral=True,delete_after=15)

    embed_id = ongoing.get("embed_message_id")
    if embed_id:
        await update_casters_embed(interaction.channel, embed_id, casters)