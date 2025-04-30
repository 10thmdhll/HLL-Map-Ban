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
        draw.text((20, y_offset + 30), f"Final Assignments: {final_assignments['team_a']} (Allied) vs {final_assignments['team_b']} (Axis)", fill="green", font=font)

    # If there is a final map, display it
    if final_map:
        draw.text((20, y_offset + 50), f"Final Map: {final_map}", fill="green", font=font)

    # Display whose turn it is to ban
    if current_turn:
        draw.text((20, y_offset + 70), f"Current Turn: {current_turn}'s turn to ban", fill="blue", font=font)

    # Save the image
    image_path = "ban_status.png"
    image.save(image_path)
    return image_path

# Store ongoing match ban states and turn order (tracked by match ID)
ongoing_bans = {}
match_turns = {}  # Key: match_id, Value: {"current_turn": "team_a" or "team_b", "host": team_a or team_b, "first_ban_team": team_a or team_b}

# Match setup logic to be triggered when a match is created
async def match_setup(ctx, team_a_name, team_b_name, title, description, selected_map, side_choice, match_id, first_ban_team=None, host_team=None):
    # Load config (region mappings)
    config = load_config()

    # Load map list from maplist.json
    map_list = load_maplist()

    # Hardcode BansAndPredictionsEnabled as "yes"
    bans_and_predictions_enabled = "yes"

    # Initialize banned maps if match is new
    if match_id not in ongoing_bans:
        ongoing_bans[match_id] = {map_info['name']: [] for map_info in map_list}

    # If a side is banned, mark the corresponding side as banned for the map
    ongoing_bans[match_id][selected_map].append(side_choice)

    # Save the updated map list
    save_maplist(map_list)

    # Check if only one valid combination remains
    valid_combinations = {}
    for map_info in map_list:
        if "Allied" not in ongoing_bans[match_id].get(map_info['name'], []) and "Axis" not in ongoing_bans[match_id].get(map_info['name'], []):
            valid_combinations[map_info['name']] = None

    # Determine final assignments if only one valid combination remains
    final_assignments = None
    final_map = None
    if len(valid_combinations) == 1:
        final_map = list(valid_combinations.keys())[0]
        final_assignments = {
            "team_a": "Allied",  # Team A gets Allied
            "team_b": "Axis",    # Team B gets Axis
        }

    # Create the ban status image
    image_path = create_ban_status_image(map_list, ongoing_bans[match_id], host_team, final_assignments, final_map, current_turn=match_turns[match_id].get("current_turn"))

    # Get the regions for each team from the config
    team_a_region = get_team_region(team_a_name, config)
    team_b_region = get_team_region(team_b_name, config)

    # Determine whether to apply extra ban or server host based on region pairing
    ban_option = determine_ban_option(team_a_region, team_b_region, config)

    # If no description is provided, default it to "No description provided"
    if not description:
        description = "No description provided"

    # Notify teams of the region assignment and ban option
    await ctx.send(f"**{title}** - {description}")
    await ctx.send(f"{team_a_name} is assigned to {team_a_region}")
    await ctx.send(f"{team_b_name} is assigned to {team_b_region}")
    await ctx.send(f"Map ban option for this match: {ban_option}")
    await ctx.send(f"Bans and predictions enabled: {bans_and_predictions_enabled}")

    # Show the selected map and the side that was chosen for banning
    await ctx.send(f"Selected map for banning: {selected_map} - Side chosen: {side_choice}")

    # Send the generated image with the ban status
    await ctx.send(file=discord.File(image_path))

    # Determine coin flip result (heads or tails)
    flip_result = random.choice(['heads', 'tails'])
    result_message = f"Coin flip result: {flip_result}"

    # Add the region info and ban option to the coin flip result
    result_message += f"\n{team_a_name} ({team_a_region}) vs {team_b_name} ({team_b_region})"
    result_message += f"\nMap ban option: {ban_option}"

    await ctx.send(result_message)

# /match_create command: Allows users to create a new match
@bot.command()
async def match_create(ctx, team_a_name: str, team_b_name: str, title: str, description: str = "No description provided"):
    """Creates a new match between two teams."""
    
    # Load config (region mappings)
    config = load_config()

    # Get the regions of both teams
    team_a_region = get_team_region(team_a_name, config)
    team_b_region = get_team_region(team_b_name, config)

    # Generate a unique match ID based on the current time or a UUID
    match_id = uuid.uuid4()

    # Generate and display the match info
    match_info = f"Match Created!\n\n**Title**: {title}\n**Team A**: {team_a_name} (Region: {team_a_region})\n**Team B**: {team_b_name} (Region: {team_b_region})\n**Description**: {description}\n\nMatch ID: {match_id}"
    await ctx.send(match_info)

    # Further setup logic (e.g., create a match state, image generation, etc.) can go here.

# /ban command: Allow users to ban a map and side, with team-specific permissions
@bot.command(name="ban")
async def ban(ctx, map: str, side: str):
    match_id = ctx.channel.id  # Using the channel ID as match ID (for simplicity)
    team_role = "team_a" if match_turns.get(match_id, {}).get("current_turn") == "team_a" else "team_b"

    # Check if user has the correct role for banning
    member = ctx.author
    role = discord.utils.get(member.roles, name=team_role)

    if not role:
        await ctx.send(f"You cannot ban right now. It's {team_role}'s turn to ban.")
        return

    # Load map list
    map_list = load_maplist()

    # Check if map is available for banning
    selected_map = next((map_info for map_info in map_list if map_info["name"] == map), None)

    if not selected_map:
        await ctx.send("This map is not available.")
        return

    # Check if the side is available
    if selected_map["options"].get(side) == "Banned":
        await ctx.send(f"The {side} side of {map} has already been banned.")
        return

    # Ban the side and mark the opposite side as banned
    selected_map["options"][side] = "Banned"
    opposite_side = "Allied" if side == "Axis" else "Axis"
    selected_map["options"][opposite_side] = "Banned"

    # Save the updated map list
    save_maplist(map_list)

    # Confirm the ban and show the updated image
    await ctx.send(f"{side} side of {map} has been banned. The {opposite_side} side is also banned.")

    # Update turn and call the match setup to generate and display the ban status image
    match_turns[match_id]["current_turn"] = "team_b" if team_role == "team_a" else "team_a"
    await match_setup(ctx, "Team A", "Team B", "Match Title", "Match Description", map, side, match_id, match_turns[match_id]["current_turn"], match_turns[match_id]["host"])

# Start the bot with your token (use an environment variable for security)
bot.run(os.getenv('DISCORD_TOKEN'))
