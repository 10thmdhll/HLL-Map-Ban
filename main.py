import os
import glob
import discord
import asyncio
import helpers
from discord import app_commands
from config import DISCORD_TOKEN
from state import load_state, list_state_files
# Import commands to register them
import commands.select_ban_mode
import commands.ban_map
import commands.match_create
import commands.match_delete
import commands.match_decide
import commands.match_time

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

load_dotenv()

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
    await tree.sync()
    # Load persisted state
    for path in list_state_files():
        ch = int(path.split("_")[1].split(".")[0])
        await load_state(ch)
    print("Bot is ready.")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)