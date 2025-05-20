import discord
from discord import app_commands
from discord.app_commands import Choice
from config import DISCORD_TOKEN
import state
# Import command handlers to register them
import commands.match_create
import commands.select_host_mode
import commands.select_ban_mode
import commands.ban_map
import commands.match_time
import commands.cleanup_match

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Register commands
from commands.match_create import match_create
from commands.select_host_mode import select_host_mode
from commands.select_ban_mode import select_ban_mode
from commands.ban_map import ban_map
from commands.match_time import match_time
from commands.cleanup_match import cleanup_match

tree.add_command(match_create)
tree.add_command(select_host_mode)
tree.add_command(select_ban_mode)
tree.add_command(ban_map)
tree.add_command(match_time)
tree.add_command(cleanup_match)

@self.tree.error
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # catch cooldowns
        if isinstance(error, app_commands.CommandOnCooldown):
            retry = error.retry_after
            # tell the user how long they’ve got to wait
            return await interaction.response.send_message(
                f"⏳ That command is on cooldown. Try again in {retry:.1f}s.",
                ephemeral=True
            )
        # re-raise unhandled errors
        raise error
        
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