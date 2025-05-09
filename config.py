import os
from dotenv import load_dotenv
from PIL import ImageFont

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set in environment")

CONFIG = {
    # Paths to search for fonts
    "font_paths": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "./assets/fonts/DejaVuSans.ttf",
    ],
    "font_size_h": 24,
    "font_size": 18,
}

# Preload fonts once
def load_fonts():
    for path in CONFIG["font_paths"]:
        if os.path.isfile(path):
            return (
                ImageFont.truetype(path, CONFIG["font_size_h"]),
                ImageFont.truetype(path, CONFIG["font_size"]),
            )
    raise FileNotFoundError(f"No valid font found in {CONFIG['font_paths']}")

HDR_FONT, ROW_FONT = load_fonts()