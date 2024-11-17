from flask import Flask, render_template, request, redirect, url_for
from nba_api.stats.endpoints import scoreboardv2, boxscoretraditionalv2, playbyplayv2, teamdetails
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from dateutil import parser
import os
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import pytz

# Load environment variables from .env file
load_dotenv()

# Access the API key
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI()

app = Flask(__name__)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/games', methods=['GET'])
def display_games():

    # Get the selected date from the form
    selected_date = request.args.get('game_date', None)
    if not selected_date:
        return "Error: No date provided."

    # Convert date to NBA API format
    try:
        game_date = datetime.strptime(
            selected_date, '%Y-%m-%d').strftime('%m/%d/%Y')
    except ValueError:
        return "Error: Invalid date format."

    # Retrieve yesterday's games using the NBA API scoreboard
    board = scoreboardv2.ScoreboardV2(game_date=game_date)
    # Retrieve the main DataFrame containing game data
    games_data = board.get_data_frames()[0]

    games = []
    for _, game in games_data.iterrows():
        # Get team abbreviations or use team IDs to map to names
        away_team_id = game["VISITOR_TEAM_ID"]
        home_team_id = game["HOME_TEAM_ID"]
        game_status = game['GAME_STATUS_TEXT']

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
            "game_time": game_time_ltz.strftime('%Y-%m-%d'),
            "game_status": game_status
        })

    # Pass game information to the template
    return render_template('games.html', games=games, game_date=selected_date)


@app.route('/generate_recap/<game_id>', methods=['GET'])
def generate_recap(game_id):
    try:
        # Fetch game data using the NBA API
        boxscore_data, play_by_play_data = fetch_nba_data(game_id)

        # Generate a game recap using the data
        summary = create_game_recap(boxscore_data, play_by_play_data)
        teams = list(boxscore_data['TEAM_ABBREVIATION'].unique())
        print(teams)
        return render_template('recap.html', summary=summary, teams=teams)

    except Exception as e:
        return render_template('recap.html', error=f"An error occurred: {str(e)}")


def get_team_name(team_id):
    # Function to map team ID to team name using teamdetails
    team_data = teamdetails.TeamDetails(team_id=team_id).get_data_frames()[0]
    team_name = team_data[team_data["TEAM_ID"]
                          == team_id]["NICKNAME"].values[0]
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
    # 1. Format box score data
    team_abbreviations = boxscore_data['TEAM_ABBREVIATION'].unique()
    team_scores = boxscore_data.groupby('TEAM_ABBREVIATION')[
        'PTS'].sum().to_dict()

    # Get top scorer details
    top_scorer = boxscore_data.loc[boxscore_data['PTS'].idxmax()]

    # Generate a box score summary
    boxscore_summary = (
        f"The game was between {team_abbreviations[0]} and {team_abbreviations[1]}. "
        f"The final score was {team_scores[team_abbreviations[0]]} to {team_scores[team_abbreviations[1]]}. "
        f"The top scorer was {top_scorer['PLAYER_NAME']} from {top_scorer['TEAM_ABBREVIATION']} "
        f"with {top_scorer['PTS']} points."
    )

    # 2. Format play-by-play data to highlight key moments
    key_moments = play_by_play_data[
        (play_by_play_data['EVENTMSGTYPE'].isin([1, 3, 5])) & (
            play_by_play_data['SCORE'] != '')
    ]
    key_moments_summary = "\n".join(
        f"- {row['PERIOD']}Q, {row['PCTIMESTRING']}: {row['HOMEDESCRIPTION'] or row['VISITORDESCRIPTION']} "
        for _, row in key_moments.iterrows()
    )

    # Combine box score and play-by-play summaries into the final prompt
    prompt = (
        f"{boxscore_summary}\n\n"
        "Here are some key moments from the game:\n"
        f"{key_moments_summary}\n\n"
        "Based on the above information, generate a detailed and engaging summary of the game as a bullet point list, highlighting key plays, turning points, and standout performances."
        "If the score was close, describe big plays from the final 5 minutes of the game."
    )

    # 3. Call the OpenAI API with the formatted prompt
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "system", "content": "You are an assistant that summarizes NBA games."},
                  {"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.7
    )

    # Get the summary from the response
    summary = response.choices[0].message.content
    print(summary)

    # Format the summary to be split into sections
    formatted_summary = summary.split('\n')
    formatted_summary = summary.split('- ')
    formatted_summary = [s.strip()
                         for s in formatted_summary if s.strip()]  # Remove any extra spaces

    return formatted_summary


if __name__ == '__main__':
    app.run(debug=True)
