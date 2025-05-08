import discord
from discord import app_commands
from state import load_state, save_state, ongoing_bans, match_turns, match_times, channel_teams, channel_decision, channel_mode
from helpers import remaining_combos
from datetime import datetime

@app_commands.command(name="ban_map")
@app_commands.describe(map="Map to ban", side="Side banning map")
async def ban_map(interaction: discord.Interaction, map: str, side: str):
    ch = interaction.channel.id
    await load_state(ch)

    # 1) Must have created a match
    if ch not in channel_teams or not channel_teams[ch]:
        return await interaction.response.send_message(
            "❌ No match created. Use /match_create.", ephemeral=True
        )
    # 2) Coin flip result must exist
    winner = channel_decision.get(ch)
    if not winner:
        return await interaction.response.send_message(
            "❌ Coin flip result missing. Use /match_create.", ephemeral=True
        )
    # 3) Ban mode must be selected
    mode = channel_mode.get(ch)
    if not mode:
        return await interaction.response.send_message(
            "❌ Ban mode not set. Use /select_ban_mode.", ephemeral=True
        )

    # Remaining combos
    rem = remaining_combos(ch)
    # Final vote when only one combo left
    if len(rem) == 1:
        final_map, _, final_side = rem[0]
        if map != final_map or side != final_side:
            return await interaction.response.send_message(
                f"❌ Final vote must be `{final_side}` on `{final_map}`.", ephemeral=True
            )
        ongoing_bans.setdefault(ch, {})[final_map] = final_side
        match_turns.setdefault(ch, []).append(side)
        match_times.setdefault(ch, []).append(datetime.utcnow().isoformat())
        await save_state(ch)
        return await interaction.response.send_message(
            f"🏁 Final vote cast: `{side}` on `{final_map}`.", ephemeral=False
        )

    # Compute loser and turn order
    sides = list({s for _, _, s in channel_teams[ch]})
    loser = sides[1] if sides[0] == winner else sides[0]
    n = len(match_turns.get(ch, []))
    if mode == "final":
        expected = loser if n % 2 == 0 else winner
    else:
        expected = winner if n == 0 else loser if n in (1, 2) else (winner if ((n - 3) % 2 == 0) else loser)

    if side != expected:
        return await interaction.response.send_message(
            f"❌ It's `{expected}`'s turn, not `{side}`.", ephemeral=True
        )

    # Validate availability
    valid = [s for (m, _, s) in rem if m == map]
    if not valid:
        return await interaction.response.send_message(
            f"❌ `{map}` cannot be banned by `{side}`.", ephemeral=True
        )

    # Record normal ban
    ongoing_bans.setdefault(ch, {})[map] = side
    match_turns.setdefault(ch, []).append(side)
    match_times.setdefault(ch, []).append(datetime.utcnow().isoformat())
    await save_state(ch)

    await interaction.response.send_message(f"✅ `{side}` banned `{map}` (Turn {n+1}).")