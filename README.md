# HLL Map Ban Bot

A Discord bot that automates competitive map‐ban sequences for Hell Let Loose (HLL), complete with:

- Region-based “Extra Ban” vs “Determine Host” logic
- Coin-flip to decide first ban or host
- Live ban-status images rendered via Pillow
- Persistent state across restarts
- Community poll at the end for everyone to vote on the match winner

---

## Features

- **Slash commands**  
  `/match_create`, `/ban_map`, `/match_decide`, `/match_delete`
- **Region pairing**  
  Extra-ban or host-decision flows driven by a simple JSON config
- **Live image updates**  
  Ban status chart with colored cells (red/orange/green) auto-resizes for Discord
- **Persistent state**  
  Saved to `state.json` so matches survive bot restarts
- **Community poll**  
  Automatically posts a “Who will win?” poll when bans complete

---

## Prerequisites

- Python 3.10+  
- A Discord application with **applications.commands** and **bot** scopes  
- Bot token with slash-command and send-message permissions  

---

## Installation

`git clone https://github.com/your-org/HLL-Map-Ban.git`
`cd HLL-Map-Ban`
`python3 -m venv venv`
`source venv/bin/activate`
`pip install -r requirements.txt`

Create a .env file:
`cp default.env .env`

Edit new .env file with discord bot token:
`DISCORD_TOKEN=your_bot_token_here`

Configuration
All settings live at the top of bot.py in the CONFIG dictionary:

CONFIG = {
  "state_file":       "state.json",
  "teammap_file":     "teammap.json",    # team→region + region×region→mode
  "maplist_file":     "maplist.json",    # list of maps
  "output_image":     "ban_status.png",
  "max_inline_width": 800,
  "quantize_colors":  64,
  "compress_level":   9,
  "optimize_png":     True,
  "row_font_size":    168,
  "header_font_size": 240,
  "pad_x_factor":     0.5,
  "pad_y_factor":     0.25,
  "font_paths": [
    "arialbd.ttf",
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
  ]
}

teammap.json setup
Team Regions: Should follow the "Team Name": "Reagion" format
Region Pairings: Region vs region settings for "DetermineHost" or "ExtraBan"

`{
  "team_regions": {
	"Esprit de Corps" : "NA",
	"MS" : "EU",
	"Climbers" : "CN"
}
  "region_pairings": {
    "NA": {
      "NA": "ExtraBan",
	  "SA": "ExtraBan",
	  "EU": "DetermineHost",
	  "CN": "ExtraBan",
	  "OCE": "ExtraBan"
    },
    "SA": {
      "NA": "ExtraBan",
	  "SA": "ExtraBan",
	  "EU": "ExtraBan",
	  "CN": "ExtraBan",
	  "OCE": "ExtraBan"
    },
	"EU": {
      "NA": "DetermineHost",
	  "SA": "ExtraBan",
	  "EU": "ExtraBan",
	  "CN": "ExtraBan",
	  "OCE": "ExtraBan"
    },
	"CN": {
      "NA": "ExtraBan",
	  "SA": "ExtraBan",
	  "EU": "ExtraBan",
	  "CN": "ExtraBan",
	  "OCE": "ExtraBan"
    },
	"OCE": {
      "NA": "ExtraBan",
	  "SA": "ExtraBan",
	  "EU": "ExtraBan",
	  "CN": "ExtraBan",
	  "OCE": "ExtraBan"
    }
  }
}`

maplist.json
Should follow: "Map Name" JSON format.  
`{
  "maps": [
    {
      "name": "Carentan – Day",
      "options": {
        "Allied": "Available",
        "Axis": "Available"
      }
    },
    {
      "name": "Carentan – Night",
      "options": {
        "Allied": "Available",
        "Axis": "Available"
      }
    }
	]
}`

Usage
Start the bot (this syncs slash commands automatically):
`python bot.py`

Create a match:

/match_create
  team_a:@Esprit de Corps
  team_b:@MS
  title:"Quarterfinal"
  description:"Map veto for quarterfinal"

Ban maps in alternating turns:

/ban_map map_name:"Carentan – Day" side:Allied
If mode is “DetermineHost”, the flip-winner runs:

/match_decide choice:ban
or
/match_decide choice:host

At final ban, bot will:

Mark remaining cells as the final choice
Update the image
Post a poll:

📊 Who will win the match?
🅰️ MS
🅱️ Esprit de Corps


Delete a match and clear state:
/match_delete


Command Reference
Command	Options	Description
/match_create	team_a, team_b, title, [description]	Create new match & coin-flip/host logic
/ban_map	map_name, side	Ban a map side (auto-bans opposite side)
/match_decide	choice ∈ {ban,host}	Flip-winner chooses first ban or hosting
/match_delete	(none)	Delete current match from this channel

All slash responses are ephemeral when appropriate to avoid channel clutter.

File Structure

HLL-Map-Ban/
├── bot.py
├── teammap.json
├── maplist.json
├── state.json          # generated
├── ban_status.png      # generated
├── requirements.txt
├── .env                # contains DISCORD_TOKEN
└── README.md

Dependencies
-discord.py
-python-dotenv
-Pillow

Install via:
`pip install -r requirements.txt`
License
MIT © 
