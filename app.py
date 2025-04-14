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

timeout = 120


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/games', methods=['GET'])
def display_games():

    # Get the selected date from the form
    selected_date = request.args.get('game_date', None)
    print(selected_date)
    if not selected_date:
        return "Error: No date provided."

    # Convert date to NBA API format
    try:
        game_date = datetime.strptime(
            selected_date, '%Y-%m-%d').strftime('%m/%d/%Y')
        print(game_date)
    except ValueError:
        return "Error: Invalid date format."

    # Retrieve games using the NBA API scoreboard
    board = scoreboardv2.ScoreboardV2(game_date=game_date, timeout=timeout)
    # Retrieve the main DataFrame containing game data
    games_data = pd.DataFrame(board.get_data_frames()[0])
    pts_data = pd.DataFrame(board.get_data_frames()[1])

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
        home_team_logo = get_team_logo(home_team_name)

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
            "home_team_logo": home_team_logo,
            "game_time": game_time_ltz.strftime('%Y-%m-%d'),
            "game_status": game_status
        })

    # Pass game information to the template
    return render_template('games.html', games=games, game_date=selected_date)


def generate_recap(game_id):
    # Fetch game data using the NBA API
    boxscore_data = get_boxscore_data(game_id)
    play_by_play_data = get_playbyplay_data(game_id)

    # Generate a game recap using the data
    summary = create_game_recap(boxscore_data, play_by_play_data)
    return summary


@app.route('/boxscore/<game_id>')
def boxscore(game_id):
    action = request.args.get('action', default=None)
    game_date = request.args.get('game_date')  # Provide a fallback date
    # Replace with your boxscore fetching logic
    boxscore_data, teams = display_boxscore(game_id)
    summary = None

    if action == 'summarize':
        # Generate the game summary (replace with your logic)
        summary = generate_recap(game_id)

    return render_template('boxscore.html',
                           game_id=game_id,
                           boxscore_data=boxscore_data,
                           summary=summary,
                           teams=teams,
                           game_date=game_date)


def display_boxscore(game_id):
    # Fetch boxscore data
    boxscore_data = get_boxscore_data(game_id)

    # drop columns that aren't needed for boxscore
    columns_to_drop = [0, 3, 4, 6, 8]
    boxscore_data = boxscore_data.drop(
        boxscore_data.columns[columns_to_drop], axis=1)
    print(boxscore_data.info())

    # change column names
    boxscore_data = boxscore_data.rename(columns={
        "TEAM_ABBREVIATION": "TEAM",
        "PLAYER_NAME": "PLAYER",
        "START_POSITION": "POS",
        "FG_PCT": "FG%",
        "FG3M": "3PM",
        "FG3A": "3PA",
        "FG3_PCT": "3P%",
        "FT_PCT": "FT%",
        "PLUS_MINUS": "+/-"
    })

    boxscore_data_dict = boxscore_data.to_dict(orient='records')

    # Prepare a mapping of team_id to team_name
    team_mapping = {
        row['TEAM_ID']: row['TEAM'] for row in boxscore_data_dict
    }

    # Send team_ids and names as a list of tuples
    teams = [{'id': team_id, 'name': name}
             for team_id, name in team_mapping.items()]

    # drop team_id
    boxscore_data = boxscore_data.drop(columns="TEAM_ID")

    # Convert the column to min:sec format
    boxscore_data['MIN'] = boxscore_data['MIN'].apply(lambda x: "0:00" if pd.isna(
        x) else f"{int(float(x.split(':')[0]))}:{int(x.split(':')[1])}")

    print(boxscore_data.info())

    # fill nan values with 0
    boxscore_data = boxscore_data.fillna(0)

    # convert floats to ints
    columns_to_convert = ["FGM", "FGA", "3PM", "3PA", "FTM", "FTA",
                          "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "PTS", "+/-"]
    boxscore_data[columns_to_convert] = boxscore_data[columns_to_convert].astype(
        int)

    # convert percentages
    boxscore_data['FG%'] = round(boxscore_data['FG%'] * 100, 2)
    boxscore_data['3P%'] = round(boxscore_data['3P%'] * 100, 2)
    boxscore_data['FT%'] = round(boxscore_data['FT%'] * 100, 2)

    # convert finals boxscore to dictionary
    boxscore_data = boxscore_data.to_dict(orient='records')

    return (boxscore_data, teams)


def get_team_logo(team_name):

    team_logos = {
        "Hawks": "https://cdn.nba.com/logos/nba/1610612737/primary/L/logo.svg",
        "Celtics": "https://cdn.nba.com/logos/nba/1610612738/primary/L/logo.svg",
        "Nets": "https://cdn.nba.com/logos/nba/1610612751/primary/L/logo.svg",
        "Hornets": "https://cdn.nba.com/logos/nba/1610612766/primary/L/logo.svg",
        "Bulls": "https://cdn.nba.com/logos/nba/1610612741/primary/L/logo.svg",
        "Cavaliers": "https://cdn.nba.com/logos/nba/1610612739/primary/L/logo.svg",
        "Mavericks": "https://cdn.nba.com/logos/nba/1610612742/primary/L/logo.svg",
        "Nuggets": "https://cdn.nba.com/logos/nba/1610612743/primary/L/logo.svg",
        "Pistons": "https://cdn.nba.com/logos/nba/1610612765/primary/L/logo.svg",
        "Warriors": "https://cdn.nba.com/logos/nba/1610612744/primary/L/logo.svg",
        "Rockets": "https://cdn.nba.com/logos/nba/1610612745/primary/L/logo.svg",
        "Pacers": "https://cdn.nba.com/logos/nba/1610612754/primary/L/logo.svg",
        "Clippers": "https://cdn.nba.com/logos/nba/1610612746/primary/L/logo.svg",
        "Lakers": "https://cdn.nba.com/logos/nba/1610612747/primary/L/logo.svg",
        "Grizzlies": "https://cdn.nba.com/logos/nba/1610612763/primary/L/logo.svg",
        "Heat": "https://cdn.nba.com/logos/nba/1610612748/primary/L/logo.svg",
        "Bucks": "https://cdn.nba.com/logos/nba/1610612749/primary/L/logo.svg",
        "Timberwolves": "https://cdn.nba.com/logos/nba/1610612750/primary/L/logo.svg",
        "Pelicans": "https://cdn.nba.com/logos/nba/1610612740/primary/L/logo.svg",
        "Knicks": "https://cdn.nba.com/logos/nba/1610612752/primary/L/logo.svg",
        "Thunder": "https://cdn.nba.com/logos/nba/1610612760/primary/L/logo.svg",
        "Magic": "https://cdn.nba.com/logos/nba/1610612753/primary/L/logo.svg",
        "76ers": "https://cdn.nba.com/logos/nba/1610612755/primary/L/logo.svg",
        "Suns": "https://cdn.nba.com/logos/nba/1610612756/primary/L/logo.svg",
        "Trail Blazers": "https://cdn.nba.com/logos/nba/1610612757/primary/L/logo.svg",
        "Kings": "https://cdn.nba.com/logos/nba/1610612758/primary/L/logo.svg",
        "Spurs": "https://cdn.nba.com/logos/nba/1610612759/primary/L/logo.svg",
        "Raptors": "https://cdn.nba.com/logos/nba/1610612761/primary/L/logo.svg",
        "Jazz": "https://cdn.nba.com/logos/nba/1610612762/primary/L/logo.svg",
        "Wizards": "https://cdn.nba.com/logos/nba/1610612764/primary/L/logo.svg"
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
    data = pd.DataFrame(get_boxscoresummary_data(game_id))

    if not data.empty:
        print(
            f"Successfully retrieved box score summary for team_id: {team_id}")
    else:
        print(f"Failed retrieving box score summary for team_id: {team_id}")

    score = data.loc[data['TEAM_ID'] == team_id]['PTS'].iloc[0]
    return score


def get_boxscore_data(game_id):
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


def get_playbyplay_data(game_id):
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


def get_boxscoresummary_data(game_id):
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
    cleaned_summary = summary.replace("- ", "").strip()
    return cleaned_summary


if __name__ == "__main__":
    # Render sets this env var; default to 5000 locally
    port = int(os.environ.get("PORT", 5000))
    # Optional: "127.0.0.1" for local, "0.0.0.0" for Render
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port)
