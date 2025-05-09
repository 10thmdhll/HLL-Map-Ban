import discord
import helpers
from discord import app_commands
from state import load_state, save_state, channel_teams, match_turns, ongoing_bans, channel_mode, channel_decision, match_times

@bot.tree.command(
    name="match_time",
    description="Set the scheduled match time"
)
@app_commands.describe(
    time="ISO-8601 datetime (with timezone) for the match -> ex. 2025-05-21T18:00:00-04:00"
)
async def match_time_cmd(
    interaction: discord.Interaction,
    time: str
) -> None:
    global team_a_name, team_b_name
    team_a_name, team_b_name = channel_teams[ch]

    ch = interaction.channel_id
    await load_state(ch)
    # Ensure there’s an active match and it’s past ban phase
    if ch not in ongoing_bans:
        return await interaction.response.send_message(
            "❌ Ban phase not complete or no active match.", 
            ephemeral=True
        )

    # Only team members may set the time
    team_roles = channel_teams[ch]
    if not any(r.name in team_roles for r in interaction.user.roles):
        return await interaction.response.send_message(
            "❌ Only players in this match may set the time.", 
            ephemeral=True
        )

    await interaction.response.defer()

    # Parse and store in UTC
    try:
        dt = parser.isoparse(time).astimezone(pytz.utc)
        match_times[ch] = dt.isoformat()
        await save_state(ch)
    except Exception as e:
        msg = await interaction.followup.send(
            f"❌ Invalid datetime: {e}", 
            ephemeral=True
        )
        return
        
    # Build the status embed
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
    embed.add_field(name="Final Ban",  value=current_name,  inline=True)
    embed.add_field(name="Stage", value="Map ban complete, time updated",  inline=False)


    # Edit the original image message with both image + embed
    await update_status_message(
        ch,
        channel_messages[ch],
        buf,
        embed=embed
    )

    await save_state(ch)
    
    # Then confirm privately
    msg = await interaction.followup.send("✅ Updated.", ephemeral=True)
    return