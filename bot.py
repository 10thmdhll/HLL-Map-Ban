import discord
import random
import json
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import os
import uuid

# Load environment variables (for Discord token)
load_dotenv()

# Define intents
intents = discord.Intents.default()
intents.message_content = True  # Allows the bot to read messages (needed for slash commands and other interactions)

# Initialize the bot with a command prefix and intents
bot = commands.Bot(command_prefix="/", intents=intents)

# Load team and region pairings from the teammap.json file
def load_config():
    with open('teammap.json', 'r') as f:
        config = json.load(f)
    return config

# Load map list from maplist.json file
def load_maplist():
    with open('maplist.json', 'r') as f:
        map_data = json.load(f)
    return map_data['maps']

# Save updated maplist.json after each ban
def save_maplist(maplist):
    with open('maplist.json', 'w') as f:
        json.dump({"maps": maplist}, f, indent=4)

# Get the region for a specific team from the config
def get_team_region(team_name, config):
    return config["team_regions"].get(team_name, "Unknown Region")

# Determine the map ban option (ExtraBan or DetermineHost) based on region pairing
def determine_ban_option(team_a_region, team_b_region, config):
    region_pairings = config["region_pairings"]

    # Check if the region pairing exists in the config
    if team_a_region in region_pairings and team_b_region in region_pairings[team_a_region]:
        mapping = region_pairings[team_a_region][team_b_region]
        if mapping == "ExtraBan":
            return "extra ban"
        elif mapping == "DetermineHost":
            return "server host"
    
    # Default if no specific pairing found
    return "server host"  # Default to "server host" if no "ExtraBan" mapping is found

# Get the Discord role for the team
async def get_team_role(ctx, team_name):
    guild = ctx.guild
    role = discord.utils.get(guild.roles, name=team_name)
    if role:
        return role
    else:
        await ctx.send(f"Role {team_name} not found!")
        return None

# Function to create the ban status image
def create_ban_status_image(map_list, banned_maps, host_team=None, final_assignments=None, final_map=None, current_turn=None):
    # Define image dimensions and properties
    width = 600
    height = len(map_list) * 50 + 50  # Height based on the number of maps
    image = Image.new('RGB', (width, height), (255, 255, 255))  # White background
    draw = ImageDraw.Draw(image)

    # Define font (use a default one if font not available)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except IOError:
        font = ImageFont.load_default()

    # Draw headers
    draw.text((20, 10), "Map Ban Status", fill="black", font=font)

    # Draw each map and its ban status
    y_offset = 50
    for map_info in map_list:
        map_name = map_info['name']
        allied_ban = "Allied" in banned_maps.get(map_name, [])
        axis_ban = "Axis" in banned_maps.get(map_name, [])

        # Determine colors
        if allied_ban and axis_ban:
            bg_color = (255, 0, 0)  # Red background for fully banned maps
            text_color = (0, 0, 0)  # Black text
        elif allied_ban or axis_ban:
            bg_color = (255, 0, 0)  # Red background for banned sides
            text_color = (0, 0, 0)  # Black text
        else:
            # Check for final map/side combination
            if final_map and map_name == final_map:
                bg_color = (0, 255, 0)  # Green background for final valid combinations
                text_color = (0, 0, 0)  # Black text
            else:
                bg_color = (255, 255, 255)  # White background for available maps
                text_color = (0, 0, 0)  # Black text

        # Draw the map row
        draw.rectangle([20, y_offset, width - 20, y_offset + 40], fill=bg_color)
        draw.text((30, y_offset + 10), f"{map_name} - Allied: {'Banned' if allied_ban else 'Available'} / Axis: {'Banned' if axis_ban else 'Available'}", fill=text_color, font=font)

        y_offset += 50

    # If a host team is set, mark them on the image
    if host_team:
        draw.text((20, y_offset + 10), f"Host Team: {host_team}", fill="green", font=font)

    # Display final assignments
    if final_assignments:
        draw.text((20, y_offset + 30), f"Final Assignments_
