from flask import Flask, jsonify, render_template, request, redirect, url_for
from nba_api.stats.endpoints import scoreboardv2, boxscoretraditionalv2, playbyplayv2, teamdetails, boxscoresummaryv2
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from dateutil import parser
import os
from dotenv import load_dotenv
import pandas as pd
import pytz

# Load environment variables from .env file
load_dotenv()

# Access the API key
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI()

app = Flask(__name__)

timeout = 60


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

    # Retrieve games using the NBA API scoreboard
    board = scoreboardv2.ScoreboardV2(game_date=game_date, timeout=timeout)
    # Retrieve the main DataFrame containing game data
    games_data = pd.DataFrame(board.get_data_frames()[0])
    pts_data = pd.DataFrame(board.get_data_frames()[1])
    print(games_data.columns)

    games = []
    for _, game in games_data.iterrows():
        # Get team abbreviations or use team IDs to map to names
        away_team_id = game["VISITOR_TEAM_ID"]
        home_team_id = game["HOME_TEAM_ID"]
        game_status = game['GAME_STATUS_TEXT']

        # Use teamdetails to get team names for IDs
        away_team_name = get_team_name(away_team_id)
        home_team_name = get_team_name(home_team_id)

        # get team logo
        away_team_logo = get_team_logo(away_team_name)

        # get team scores
        home_score = pts_data.loc[pts_data['TEAM_ID']
                                  == home_team_id]['PTS'].values[0]
        away_score = pts_data.loc[pts_data['TEAM_ID']
                                  == away_team_id]['PTS'].values[0]

        # Convert game time to local timezone
        game_time_ltz = parser.parse(game["GAME_DATE_EST"]).replace(
            tzinfo=timezone.utc).astimezone(tz=None)
        games.append({
            "game_id": game['GAME_ID'],
            "away_team": away_team_name,
            "home_team": home_team_name,
            "away_score": away_score,
            "home_score": home_score,
            "away_team_logo": away_team_logo,
            "game_time": game_time_ltz.strftime('%Y-%m-%d'),
            "game_status": game_status
        })

    # Pass game information to the template
    return render_template('games.html', games=games, game_date=selected_date)


@app.route('/generate_recap/<game_id>', methods=['GET'])
def generate_recap(game_id):
    # Fetch game data using the NBA API
    boxscore_data = fetch_boxscore_data(game_id)
    play_by_play_data = fetch_playbyplay_data(game_id)
    boxscore_summary_data = fetch_boxscoresummary_data(game_id)

    home_team = boxscore_summary_data.iloc[0]['TEAM_NICKNAME']
    away_team = boxscore_summary_data.iloc[1]['TEAM_NICKNAME']
    home_score = boxscore_summary_data.iloc[0]["PTS"]
    away_score = boxscore_summary_data.iloc[1]["PTS"]

    teams = [home_team, away_team]
    scores = [home_score, away_score]

    # Generate a game recap using the data
    summary = create_game_recap(boxscore_data, play_by_play_data)
    print(teams)
    return jsonify({"text": summary})


def get_team_logo(team_name):

    team_logos = {
        "Lakers": "https://content.sportslogos.net/logos/6/237/full/los_angeles_lakers_logo_primary_2024_sportslogosnet-7324.png"
        # Add all other teams
    }

    if team_name in team_logos:
        logo_url = team_logos[team_name]
    else:
        logo_url = None
        print("no logo found for this team")

    return logo_url


def get_team_name(team_id):
    """
    Function to map team ID to team name using teamdetails.
    Args:
        team_id (int): The ID of the team.
        timeout (int): The maximum time (in seconds) to wait for the API response.
    Returns:
        str: The team's nickname.
    """
    try:
        # Fetch team details with a specified timeout
        team_data = pd.DataFrame(teamdetails.TeamDetails(
            team_id=team_id, timeout=timeout).get_data_frames()[0])

        # Extract and return the team nickname
        team_name = team_data[team_data["TEAM_ID"]
                              == team_id]["NICKNAME"].values[0]
        return team_name

    except Exception as e:
        print(f"Error fetching team name: {e}")
        return None


def get_team_score(game_id, team_id):
    # Fetch game data using the NBA API
    data = pd.DataFrame(fetch_boxscoresummary_data(game_id))

    if not data.empty:
        print(
            f"Successfully retrieved box score summary for team_id: {team_id}")
    else:
        print(f"Failed retrieving box score summary for team_id: {team_id}")

    score = data.loc[data['TEAM_ID'] == team_id]['PTS'].iloc[0]
    return score


def fetch_boxscore_data(game_id):
    # Fetch box score data
    try:
        boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(
            game_id=game_id, timeout=timeout)
        data_frames = boxscore.get_data_frames()
        if data_frames:
            # Get the main boxscore DataFrame
            boxscore_data = pd.DataFrame(boxscore.get_data_frames()[0])
            return boxscore_data
        else:
            print("No data available for the given game ID.")
            return None
    except KeyError as ke:
        print(f"KeyError: {ke}")
        print("Response structure may have changed or data is unavailable.")
        return None
    except Exception as e:
        print(f"Error fetching boxscore data: {e}")
        return None


def fetch_playbyplay_data(game_id):
    try:
        play_by_play = playbyplayv2.PlayByPlayV2(
            game_id=game_id, timeout=timeout)
        data_frames = play_by_play.get_data_frames()
        if data_frames:
            # Get the main boxscore DataFrame
            play_by_play_data = pd.DataFrame(play_by_play.get_data_frames()[0])
            return play_by_play_data
        else:
            print("No data available for the given game ID.")
            return None
    except KeyError as ke:
        print(f"KeyError: {ke}")
        print("Response structure may have changed or data is unavailable.")
        return None
    except Exception as e:
        print(f"Error fetching boxscore data: {e}")
        return None


def fetch_boxscoresummary_data(game_id):
    try:
        boxscore_summary = boxscoresummaryv2.BoxScoreSummaryV2(
            game_id=game_id, timeout=timeout)
        data_frames = boxscore_summary.get_data_frames()
        if data_frames:
            # Get the main boxscore DataFrame
            boxscore_summary_data = pd.DataFrame(
                boxscore_summary.get_data_frames()[5])
            return boxscore_summary_data
        else:
            print("No data available for the given game ID.")
            return None
    except KeyError as ke:
        print(f"KeyError: {ke}")
        print("Response structure may have changed or data is unavailable.")
        return None
    except Exception as e:
        print(f"Error fetching boxscore data: {e}")
        return None


def create_game_recap(boxscore_data, play_by_play_data):
    # 1. Format box score data
    team_abbreviations = boxscore_data['TEAM_ABBREVIATION'].unique()
    team_scores = boxscore_data.groupby('TEAM_ABBREVIATION')[
        'PTS'].sum().to_dict()

    # Get top scorer details
    top_scorer = boxscore_data.loc[boxscore_data['PTS'].idxmax()]

    # Generate a box score summary
    boxscore_summary = (
        f"The game was between {team_abbreviations[0]} and {
            team_abbreviations[1]}. "
        f"The final score was {team_scores[team_abbreviations[0]]} to {
            team_scores[team_abbreviations[1]]}. "
        f"The top scorer was {top_scorer['PLAYER_NAME']} from {
            top_scorer['TEAM_ABBREVIATION']} "
        f"with {top_scorer['PTS']} points."
    )

    # 2. Format play-by-play data to highlight key moments
    key_moments = play_by_play_data[
        (play_by_play_data['EVENTMSGTYPE'].isin([1, 3, 5])) & (
            play_by_play_data['SCORE'] != '')
    ]
    key_moments_summary = "\n".join(
        f"- {row['PERIOD']}Q, {row['PCTIMESTRING']
                               }: {row['HOMEDESCRIPTION'] or row['VISITORDESCRIPTION']} "
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
    cleaned_summary = summary.replace("- ", "").strip()
    return cleaned_summary


if __name__ == '__main__':
    app.run(debug=True)
