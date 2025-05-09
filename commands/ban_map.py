from datetime import datetime
import discord
from discord import app_commands
import state
from helpers import format_timestamp, remaining_combos

@app_commands.command(name="ban_map")
@app_commands.describe(
    map_name="Map to ban",
    side="Team side identifier"
)
async def ban_map(
    interaction: discord.Interaction,
    map_name: str,
    side: str
):
    """Record a map ban and update turn index based on remaining combos."""
    channel_id = interaction.channel.id
    await state.load_state(channel_id)
    ongoing = state.ongoing_events.setdefault(channel_id, {})

    # Determine remaining combos
    rem = remaining_combos(channel_id)
    # Validate chosen combo is available
    if (map_name, side) not in [(m, s) for m, _, s in rem]:
        return await interaction.response.send_message(
            f"❌ Invalid ban: {map_name} ({side}) is not available.", ephemeral=True
        )

    # Record ban
    bans = ongoing.setdefault("bans", [])
    ts = datetime.utcnow().isoformat() + 'Z'
    bans.append({"map": map_name, "side": side, "timestamp": ts})
    ongoing["current_turn_index"] = len(bans) - 1

    # Track manual bans per team
    tb = ongoing.setdefault(map_name, {"team_a": {"manual": [], "auto": []}, "team_b": {"manual": [], "auto": []}})
    # Determine which team_key
    # Assuming side maps uniquely to team_key context; here we store under both teams for example
    if "team_a" in ongoing.get("teams", []):
        tb_key = "team_a"
    else:
        tb_key = "team_b"
    tb[tb_key]["manual"].append(side)

    await state.save_state(channel_id)
    await interaction.response.send_message(
        f"{side} banned {map_name} at {format_timestamp(ts)}.")