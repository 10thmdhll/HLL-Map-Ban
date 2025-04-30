Instructions for setting up the bot and running it.

# Discord Map Ban Bot

This bot manages a map banning system for team-based games like "Hell Let Loose". It alternates between two teams to ban sides (Allied/Axis) of maps. The bot generates an image showing the status of bans, team assignments, and more.

## Setup

### Prerequisites
- Python 3.8 or higher
- A Discord bot token

### Installation

1. Clone the repository or create a new project folder.
```git clone https://github.com/10thmdhll/HLL-Map-Ban```

	`cd HLL-Map-Ban`

2. Create a virtual environment:
```python -m venv venv```

3. Activate the virtual environment:
- Windows: `venv\Scripts\activate`
- Mac/Linux: `source venv/bin/activate`

4. Install dependencies:
```pip install -r requirements.txt```

5. Create a `.env` file with your bot token:
```cp default.env .env```

6. Edit the .env file and insert your bot token.
```vi .env```

```DISCORD_TOKEN=your_discord_bot_token```

7. Running the Bot

     (optional but recommended) Create a screen dedicated to the bot
```screen -S mapban```
```source venv/bin/activate```
```python bot.py```

Ensure that you invite the bot to your server and use /match_create and /ban commands to start banning maps and assigning teams.