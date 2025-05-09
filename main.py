import os
import discord
from discord import app_commands
from config import DISCORD_TOKEN
from state import load_state, list_state_files

# Import commands to register them
from commands.select_ban_mode import select_ban_mode
from commands.ban_map import ban_map
from commands.match_create import match_create
from commands.cleanup_match import cleanup_match
from commands.match_delete import match_delete
from commands.match_time import match_time

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ─── Register Slash Commands ───────────────────────────────────────────────────
tree.add_command(select_ban_mode)
tree.add_command(ban_map)
tree.add_command(match_create)
tree.add_command(cleanup_match)
tree.add_command(match_delete)
tree.add_command(match_time)

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: Exception
) -> None:
    if isinstance(error, discord.errors.NotFound):
        return
    raise error

@bot.event
async def on_ready():
    # Sync with Discord and load persisted state
    await tree.sync()
    for path in list_state_files():
        # Extract channel ID from filename: state_<channel>.json
        ch = int(os.path.basename(path).split('_')[1].split('.')[0])
        await load_state(ch)
    print("Bot is ready.")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)