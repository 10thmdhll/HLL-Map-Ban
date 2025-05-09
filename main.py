import discord
from discord import app_commands
from config import DISCORD_TOKEN
import state
# Import command handlers to register them\ nimport commands.match_create
import commands.select_ban_mode
import commands.ban_map
import commands.match_time
import commands.cleanup_match

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Register commands
tree.add_command(commands.match_create.match_create)
tree.add_command(commands.select_ban_mode.select_ban_mode)
tree.add_command(commands.ban_map.ban_map)
tree.add_command(commands.match_time.match_time)
tree.add_command(commands.cleanup_match.cleanup_match)

@bot.event
async def on_ready():
    await tree.sync()
    # Load persisted state for all channels
    for path in state.list_state_files():
        channel_id = int(path.split('_')[1].split('.')[0])
        await state.load_state(channel_id)
    print("Bot is ready.")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)