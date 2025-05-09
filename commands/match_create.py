import uuid
import datetime
import discord
from discord import app_commands
import state

@app_commands.command(name="match_create")
@app_commands.describe(
    role_a="Discord role for Team A",
    role_b="Discord role for Team B"
)
async def match_create(interaction: discord.Interaction, role_a: discord.Role, role_b: discord.Role):
    """Initialize a new match and perform coin flip."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    match = {
        "match_id": str(uuid.uuid4()),
        "created_at": datetime.datetime.utcnow().isoformat() + 'Z',
        "teams": [role_a.id, role_b.id],
        # coin_flip to be filled next
    }
    ongoing_events = state.ongoing_events.setdefault(channel_id, {})
    ongoing_events.update(match)
    # Perform coin flip
    winner = role_a if uuid.uuid4().int % 2 == 0 else role_b
    loser  = role_b if winner == role_a else role_a
    ongoing_events["coin_flip"] = {
        "winner": winner.id,
        "loser": loser.id,
        "timestamp": datetime.datetime.utcnow().isoformat() + 'Z'
    }
    await state.save_state(channel_id)
    await interaction.response.send_message(
        f"Match created! Coin flip: {winner.name} won.")