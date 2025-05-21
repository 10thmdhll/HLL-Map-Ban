import discord
from discord import app_commands
import state
from helpers import format_timestamp, update_mt_embed
from dateutil.parser import isoparse
from datetime import timezone
from datetime import datetime

@app_commands.command(
    name="match_time",
    description="Set the scheduled time"
)
@app_commands.describe(
    time="ISO-8601 datetime WITH timezone, e.g. 2025-05-21T18:00:00-04:00"
)
async def match_time(
    interaction: discord.Interaction,
    time: str
) -> None:
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.get(channel_id, {})
    team_roles = ongoing.get("teams", [])

    # ─── Permission check ────────────────────────────────────────
    # ensure the caller has one of those team roles
    if not any(r.id in team_roles for r in interaction.user.roles):
        return await interaction.response.send_message(
            "❌ You can’t set the match time.", ephemeral=True
        )

    # ─── Defer so we can follow up multiple times ─────────────────
    await interaction.response.defer(ephemeral=True)

    # ─── Parse the ISO-8601 timestamp into UTC ────────────────────
    try:
        dt = isoparse(time).astimezone(timezone.utc)
    except Exception:
        return await interaction.followup.send(
            "❌ Invalid datetime format. Please use ISO-8601 with timezone, e.g. `2025-05-21T18:00:00-04:00`.",
            ephemeral=True
        )

    # ─── Store and update the embed ───────────────────────────────
    ongoing["scheduled_time"] = dt.isoformat()
    await state.save_state(channel_id)

    embed_msg_id = ongoing.get("embed_message_id")
    if embed_msg_id:
        await update_mt_embed(
            interaction.channel,
            embed_msg_id,
            dt.isoformat()
        )

    # ─── Final confirmation ────────────────────────────────────────
    human = dt.strftime("%Y-%m-%d %H:%M UTC")
    await interaction.followup.send(
        f"🕒 Match time set to **{human}** (UTC)", ephemeral=True
    )