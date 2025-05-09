import uuid
import datetime
import discord
from discord import app_commands
import state

@app_commands.command(name="match_create")
@app_commands.describe(
    role_a="Team A role",
    role_b="Team B role"
)
async def match_create(interaction: discord.Interaction, role_a: discord.Role, role_b: discord.Role):
    """Initialize a match with a coin flip and create status embed."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})
    ongoing["match_id"] = str(uuid.uuid4())
    ongoing["created_at"] = datetime.datetime.utcnow().isoformat() + 'Z'
    ongoing["teams"] = [role_a.id, role_b.id]
    # coin flip
    winner = role_a if uuid.uuid4().int % 2 == 0 else role_b
    loser = role_b if winner == role_a else role_a
    ongoing["coin_flip"] = {"winner": winner.id, "loser": loser.id, "timestamp": datetime.datetime.utcnow().isoformat() + 'Z'}
    # initialize other fields
    ongoing["host_or_mode_choice"] = {}
    ongoing["host_role"] = None
    ongoing["ban_mode"] = None
    ongoing["bans"] = []
    ongoing["current_turn_index"] = 0
    ongoing["scheduled_time"] = "TBD"
    ongoing["casters"] = {"team_a": None, "team_b": None}
    ongoing["additional_casters"] = []
    ongoing["update_history"] = []
    ongoing["predictions_poll"] = {}
    ongoing["embed_message_id"] = None
    await state.save_state(channel_id)
    await interaction.response.send_message(f"Match created! Coin-flip winner: {winner.name}.")