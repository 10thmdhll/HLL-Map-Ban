import discord
from discord import app_commands
from state import load_state, save_state, channel_teams, channel_mode

@app_commands.command(name="select_ban_mode")
@app_commands.describe(option="Choose ban mode for this match")
@app_commands.choices(option=[
    app_commands.Choice(name="Final Ban", value="final"),
    app_commands.Choice(name="Double Ban", value="double"),
])
async def select_ban_mode(interaction: discord.Interaction, option: str):
    ch = interaction.channel.id
    await load_state(ch)

    # Ensure match exists and coin flip done
    if ch not in channel_teams:
        return await interaction.response.send_message(
            "❌ No match created. Use /match_create first.", ephemeral=True
        )
    if channel_decision.get(ch) is None:
        return await interaction.response.send_message(
            "❌ Coin flip not set. Coin flip occurs in /match_create.", ephemeral=True
        )

    # Set mode
    channel_mode[ch] = option
    await save_state(ch)
    await interaction.response.send_message(f"✅ Ban mode set to '{option}'.", ephemeral=True)