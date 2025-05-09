import discord
from discord import app_commands
from state import load_state, match_times

@app_commands.command(name="match_time")
async def match_time(interaction: discord.Interaction):
    """
    Shows a list of timestamps for each ban/turn in the match.
    """
    ch = interaction.channel.id
    await load_state(ch)
    times = match_times.get(ch, [])
    if not times:
        return await interaction.response.send_message(
            "⏱ No bans recorded yet.", ephemeral=True
        )
    formatted = "\n".join(f"{i+1}: {t}" for i, t in enumerate(times))
    await interaction.response.send_message(
        f"⏱** Ban timestamps:**\n{formatted}", ephemeral=False
    )