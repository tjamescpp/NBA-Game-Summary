from flask import Flask, render_template, request, redirect, url_for
from nba_api.stats.endpoints import scoreboardv2, boxscoretraditionalv2, playbyplayv2, teamdetails
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from dateutil import parser
import os
from dotenv import load_dotenv
import pandas as pd
import numpy as np

# Load environment variables from .env file
load_dotenv()

# Access the API key
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI()

app = Flask(__name__)


@app.route('/')
def display_games():
    # Calculate yesterday's date
    yesterday = datetime.now() - timedelta(days=1)
    yesterday_str = yesterday.strftime('%m/%d/%Y')

    # Retrieve yesterday's games using the NBA API scoreboard
    board = scoreboardv2.ScoreboardV2(game_date=yesterday_str)
    # Retrieve the main DataFrame containing game data
    games_data = board.get_data_frames()[0]

    games = []
    for _, game in games_data.iterrows():
        # Get team abbreviations or use team IDs to map to names
        away_team_id = game["VISITOR_TEAM_ID"]
        home_team_id = game["HOME_TEAM_ID"]

        # Use teamdetails to get team names for IDs
        away_team_name = get_team_name(away_team_id)
        home_team_name = get_team_name(home_team_id)

        # Convert game time to local timezone
        game_time_ltz = parser.parse(game["GAME_DATE_EST"]).replace(
            tzinfo=timezone.utc).astimezone(tz=None)
        games.append({
            "game_id": game['GAME_ID'],
            "away_team": away_team_name,
            "home_team": home_team_name,
            "game_time": game_time_ltz.strftime('%Y-%m-%d %I:%M %p')
        })

    # Render the games on the main page
    return render_template('index.html', games=games)


@app.route('/generate_recap/<game_id>')
def generate_recap(game_id):
    try:
        # Fetch game data using the NBA API
        boxscore_data, play_by_play_data = fetch_nba_data(game_id)

        # Generate a game recap using the data
        summary = create_game_recap(boxscore_data, play_by_play_data)
        return render_template('recap.html', summary=summary)

    except Exception as e:
        return render_template('recap.html', error=f"An error occurred: {str(e)}")


def get_team_name(team_id):
    # Function to map team ID to team name using teamdetails
    team_data = teamdetails.TeamDetails(team_id=team_id).get_data_frames()[0]
    team_name = team_data[team_data["TEAM_ID"]
                          == team_id]["ABBREVIATION"].values[0]
    return team_name


def fetch_nba_data(game_id):
    # Fetch box score data
    boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id)
    # Get the main boxscore DataFrame
    boxscore_data = boxscore.get_data_frames()[0]

    # Fetch play-by-play data
    play_by_play = playbyplayv2.PlayByPlayV2(game_id=game_id)
    # Get play-by-play DataFrame
    play_by_play_data = play_by_play.get_data_frames()[0]

    return boxscore_data, play_by_play_data


def create_game_recap(boxscore_data, play_by_play_data):
    # Extract key information to include in the prompt
    team_abbreviations = boxscore_data['TEAM_ABBREVIATION'].unique()
    top_scorer = boxscore_data.loc[boxscore_data['PTS'].idxmax()]
    team_scores = boxscore_data.groupby('TEAM_ABBREVIATION')[
        'PTS'].sum().to_dict()

    # Prepare a prompt summarizing the game
    prompt = (
        f"The game was between {team_abbreviations[0]} and {team_abbreviations[1]}. "
        f"The final score was {team_scores[team_abbreviations[0]]} to {team_scores[team_abbreviations[1]]}. "
        f"The top scorer was {top_scorer['PLAYER_NAME']} from {top_scorer['TEAM_ABBREVIATION']} with {top_scorer['PTS']} points."
        " Summarize the key moments from the game play-by-play data, focusing on exciting plays and turning points."
    )

    # Chat-based API call
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",  # Chat model
        messages=[{"role": "system", "content": "You are an assistant that summarizes NBA games."},
                  {"role": "user", "content": [{"type": "text", "text": prompt}]}],  # User message
        max_tokens=200,
        temperature=0.7
    )

    # Get the summary from the response
    summary = response.choices[0].message.content
    print(summary)

    # Render the recap.html template with the summary
    # return render_template('recap.html', summary=summary)
    return summary


if __name__ == '__main__':
    app.run(debug=True)
