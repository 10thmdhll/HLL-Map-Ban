import json
import discord
import asyncio
import random
import helpers
from discord import app_commands
from state import load_state, save_state, channel_teams, match_turns, ongoing_bans, channel_mode, channel_decision, match_times
from PIL import Image, ImageDraw, ImageFont
from typing import List, Tuple, Optional, Literal, Dict, Union

@bot.tree.command(
    name="match_decide",
    description="Choose whether the flip-winner bans first or hosts first if no Middle Ground Rule"
)
@app_commands.describe(
    choice="If ‘ban’, flip-winner bans first; if ‘host’, flip-winner hosts and other side bans first"
)
async def match_decide(
    interaction: discord.Interaction,
    choice: Literal["ban", "host"]
) -> None:
    global team_a_name, team_b_name
    team_a_name, team_b_name = channel_teams[ch]

    ch = interaction.channel_id
    # 1) Ensure a match exists
    if ch not in channel_messages:
        return await interaction.response.send_message(
            "❌ No active match in this channel.", ephemeral=True
        )

    # 2) Restrict to players in the two teams
    team_roles = channel_teams.get(ch, ())
    if not any(r.name in team_roles for r in interaction.user.roles):
        return await interaction.response.send_message(
            "❌ Only players in this match may decide.", ephemeral=True
        )

    # 3) Acknowledge to allow processing
    await interaction.response.defer()

    # 4) Record the decision
    channel_decision[ch] = choice

    # 5) Compute first-ban turn
    flip_key = channel_flip[ch]  # “team_a” or “team_b”
    if choice == "ban":
        # flip-winner bans first
        match_turns[ch] = flip_key
    else:
        # flip-winner hosts, so the other team bans first
        match_turns[ch] = "team_b" if flip_key == "team_a" else "team_a"

    await save_state(ch)

    # 6) Rebuild the updated status image
    buf = create_ban_image_bytes(
        maps=load_maplist(),
        bans=ongoing_bans[ch],
        mode=channel_mode[ch],
        flip_winner=channel_flip[ch],
        host_key=channel_host[ch],
        decision_choice=channel_decision[ch],
        current_turn=match_turns[ch],
        match_time_iso=match_times.get(ch),
        final=False
    )

    # 7) Build the status embed
    A = team_a_name; B = team_b_name
    coin_winner = A if channel_flip[ch]=="team_a" else B
    host_name  = channel_host[ch]
    mode       = channel_mode[ch]
    # Safely format match time, skipping placeholders
    match_time = match_times.get(ch)
    if match_time and match_time not in ("Undecided", "TBD"):
        try:
            dt = parser.isoparse(match_time).astimezone(pytz.timezone(CONFIG["user_timezone"]))
            time_str = dt.strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            time_str = "Undecided"
    else:
        time_str = "Undecided"
    current_key = match_turns.get(ch)
    current_name= A if current_key=="team_a" else B

    embed = discord.Embed(title="Match Status")
    embed.add_field(name="Team A: ",  value=team_a_name,  inline=True)
    embed.add_field(name="Team B: ",  value=team_b_name,  inline=True)
    embed.add_field(name="Flip Winner",   value=coin_winner,   inline=True)
    embed.add_field(name="Map Host",      value=host_name,     inline=True)
    embed.add_field(name="Mode",          value=mode,          inline=True)
    embed.add_field(name="Match Time",    value=time_str,      inline=True)
    embed.add_field(name="Current Turn",  value=current_name,  inline=True)
    embed.add_field(name="Stage", value="Starting",  inline=False)


    # 8) Edit the original image message with both image + embed
    await update_status_message(
        ch,
        channel_messages[ch],
        buf,
        embed=embed
    )

    # Then confirm privately
    msg = await interaction.followup.send("✅ Updated.", ephemeral=True)
    asyncio.create_task(delete_later(msg, 5.0))
    return