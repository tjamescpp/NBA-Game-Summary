from flask import Flask, render_template, request, jsonify
from nba_api.stats.endpoints import boxscoretraditionalv2, playbyplayv2
import openai

app = Flask(__name__)

# Set up OpenAI API key (you could also load this from an environment variable for security)
openai.api_key = "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"


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


def generate_recap(boxscore_data, play_by_play_data):
    # Extract key information to include in the prompt
    team_abbreviations = boxscore_data['TEAM_ABBREVIATION'].unique()
    top_scorer = boxscore_data.loc[boxscore_data['PTS'].idxmax()]
    team_scores = boxscore_data.groupby('TEAM_ABBREVIATION')[
        'PTS'].sum().to_dict()

    # Prepare a prompt summarizing the game
    prompt = (
        f"The game was between {team_abbreviations[0]} and {
            team_abbreviations[1]}. "
        f"The final score was {team_scores[team_abbreviations[0]]} to {
            team_scores[team_abbreviations[1]]}. "
        f"The top scorer was {top_scorer['PLAYER_NAME']} from {
            top_scorer['TEAM_ABBREVIATION']} with {top_scorer['PTS']} points."
        " Summarize the key moments from the game play-by-play data, focusing on exciting plays and turning points."
    )

    # Call OpenAI API to generate a summary
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.7
    )

    return response.choices[0].message['content'].strip()


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        game_id = request.form.get('game_id')
        try:
            # Fetch game data using the NBA API
            boxscore_data, play_by_play_data = fetch_nba_data(game_id)

            # Generate a game recap using the data
            recap = generate_recap(boxscore_data, play_by_play_data)
            return render_template('index.html', recap=recap)

        except Exception as e:
            return render_template('index.html', error=f"An error occurred: {str(e)}")

    return render_template('index.html')


if __name__ == '__main__':
    app.run(debug=True)
