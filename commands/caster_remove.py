from typing import Optional
import discord
from discord import app_commands
import state
from helpers import update_casters_embed

@app_commands.command(name="caster_remove",description="Remove a link from the match")
@app_commands.describe(member="Which link to remove")
async def caster_remove(interaction: discord.Interaction,member: str):
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})
    casters = ongoing.get("casters")
    if casters is None:
        casters = []
        ongoing["casters"] = casters
        
    if member not in casters:
        return await interaction.response.send_message(f"❌ {member} isn't in the casters list.",ephemeral=True,delete_after=15)

    casters.remove(member)
    await state.save_state(channel_id)

    await interaction.response.send_message(f"🗑️ Removed {member} from casters.",ephemeral=True,delete_after=15)

    embed_id = ongoing.get("embed_message_id")
    if embed_id:
        await update_casters_embed(interaction.channel, embed_id, casters)