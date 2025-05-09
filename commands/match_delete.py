import discord
from discord import app_commands
from state import load_state, save_state, ongoing_bans, match_turns, match_times, channel_teams, channel_decision, channel_mode

@bot.tree.command(name="match_delete", description="End and remove the current match")
async def match_delete(interaction: discord.Interaction) -> None:
    ch = interaction.channel_id
    await load_state(ch)
    
    # Ensure there’s an active match
    if ch not in channel_messages:
        return await interaction.response.send_message(
            "❌ No active match to delete in this channel.", ephemeral=True
        )

    await interaction.response.defer()

    # Delete the original match image message
    msg_id = channel_messages.get(ch)
    if msg_id:
        try:
            channel = bot.get_channel(ch)
            msg = await channel.fetch_message(msg_id)
            await msg.delete()
        except Exception:
            pass  # ignore if already deleted or missing

    # Clear all per‐channel states
    for state_dict in (
        ongoing_bans,
        match_turns,
        match_times,
        channel_teams,
        channel_messages,
        channel_flip,
        channel_decision,
        channel_mode,
        channel_host
    ):
        state_dict.pop(ch, None)
    await save_state(ch)

    # Confirm deletion to the user
    msg = await interaction.followup.send("✅ Match has been deleted and state cleared.", ephemeral=True)
    return