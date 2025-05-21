import discord
from discord import app_commands
import state
from helpers import format_timestamp, update_mt_embed
from datetime import datetime

@app_commands.command(name="match_time",description="Set the scheduled time")
@app_commands.describe(
    time="ISO-8601 datetime (with timezone) for the match -> ex. 2025-05-21T18:00:00-04:00"
)
async def match_time(
    interaction: discord.Interaction,
    time: str
) -> None:
    
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.get(channel_id, {})
    team_roles = ongoing["teams"]
    
    
    # Check if the invoking user has that role
    if (team_roles[0] or team_roles[1]) not in [r.id for r in interaction.user.roles]:
        return await interaction.response.send_message(f"❌ You can’t set the match time.",ephemeral=True)

    # 3) Acknowledge so we can take our time
    await interaction.response.defer()

    # 4) Parse and store in UTC
    try:
        dt = parser.isoparse(time).astimezone(pytz.utc)
        ongoing["scheduled_time"] = dt.isoformat()
        state.save_state(channel_id)
        embed_msg_id = ongoing.get("embed_message_id")
        await update_mt_embed(interaction.channel, embed_msg_id, dt.isoformat())
    except Exception as e:
        msg = await interaction.followup.send(
            f"❌ Invalid datetime: {e}", 
            ephemeral=True
        )
        return