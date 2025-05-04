# HLL Map Ban Bot

A Discord bot that automates competitive map‐ban sequences for Hell Let Loose (HLL), complete with:

- Region-based “Extra Ban” vs “Determine Host” logic
- Coin-flip to decide first ban or host
- Live ban-status images rendered via Pillow
- Community poll at the end for everyone(must be able to see the map ban channel) to vote on the match winner

---

## Features

- **Slash commands**  
  `/match_create`, `/ban_map`, `/match_decide`, `/match_delete`, `/match_time`
- **Region pairing**  
  Extra-ban or host-decision flows driven by a simple JSON config
- **Live image updates**  
  Ban status chart with colored cells (red/orange/green) auto-resizes for Discord
- **Community poll**  
  Automatically posts a “Who will win?” poll when bans complete

---

## Prerequisites

- Python 3.10+  
- A Discord application with **applications.commands** and **bot** scopes  
- Bot token with slash-command and send-message permissions  

---

## Installation

```git clone (https://github.com/10thmdhll/HLL-Map-Ban)```
```cd HLL-Map-Ban```
```python3 -m venv venv```
```source venv/bin/activate```
```pip install -r requirements.txt```

Create a .env file:
`cp default.env .env`

Edit new .env file with discord bot token:
`DISCORD_TOKEN=your_bot_token_here`

Configuration
All settings live at the top of bot.py in the CONFIG dictionary:
`cp maplist_example.json maplist.json`

`cp teammap_example.json teammap.json`

Use the 2 files just created to complete the map list and region mappings.
Example files can be kept for reference incase changes are required.

teammap.json setup
Team Regions: Should follow the "Team Name": "Reagion" format
Region Pairings: Region vs region settings for "DetermineHost" or "ExtraBan"

Options for region pairings are "ExtraBan" and "DetermineHost"
ExtraBan will move directly to the coinflip and the winner will have the first ban.
DetermineHost will require the coinflip winner to use /match_decide choice:(ban/host) prior to the banning process.
	If ban: same behavior as winning the ExtraBan coinflip
 	If host: that team will pick the game server location and the first ban will pass to the other team.
  
Ensure all combinations are mapped correctly for the behavior you wish.
`{
  "team_regions": {
	"TEAM ROLE NAME IN DISCORD" : "NA",
	"TEAM2 ROLE NAME IN DISCORD" : "EU"
}
  "region_pairings": {
    "NA": {
      "NA": "ExtraBan",
	  "SA": "ExtraBan",
	  "EU": "DetermineHost",
	  "CN": "ExtraBan",
	  "OCE": "ExtraBan"
   	}
    }
}
    ...`

Usage
Start the bot (this syncs slash commands automatically):
`cd HLL-Map-Ban`
`source venv/bin/activate`
`python bot.py`

Create a match:
/match_create
  team_a:@Role1
  team_b:@Role2

Delete a match and clear state:
/match_delete

Decide between first ban or server host based on pairings
/match_decide choice:(ban/host)

Ban a map and side
/ban_map map: side:

Set match start time: (after map ban is complete)
/match_time time: (example string 2025-05-25T19:00-04:00)
	YYYY-MM-DDTHH:MM-TZDifferenceFromUTC
 	2025-05-25T19:00-04:00   5/25/2025 @ 7PM EDT

License
MIT © 
