import os
from dotenv import load_dotenv
from PIL import ImageFont

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set in environment")

CONFIG = {
    "teammap_file":  "teammap.json",
    "maplist_file":  "maplist.json",
    "output_image":  "ban_status.png",
    "user_timezone": "America/New_York",
    "max_inline_width": 800,
    "font_size_h":      36,
    "font_size":        24,
    "font_paths": [
        "arialbd.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
}

# Preload fonts once and expose
font_file = next((p for p in CONFIG["font_paths"] if os.path.isfile(p)), None)
if not font_file:
    raise RuntimeError(f"No valid font found in {CONFIG['font_paths']}")

HDR_FONT = ImageFont.truetype(font_file, CONFIG["font_size_h"])
ROW_FONT = ImageFont.truetype(font_file, CONFIG["font_size"])