import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
import json
import openai
import os
import sys
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials



TOKEN_FILE = 'token.json'
# Load environment variables from .env file
load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# -------- YouTube API settings --------
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRETS_FILE = "client_secrets.json"  # <-- Your OAuth file from Google Cloud Console


def get_latest_video_id(channel_url):
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'skip_download': True,
        'playlistend': 1,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
        if 'entries' in info and len(info['entries']) > 0:
            video_entry = info['entries'][0]
            return video_entry['id'], video_entry.get('title', 'Title not available')
        else:
            raise Exception("No videos found on the channel.")
        
def get_video_description(video_id):
    youtube = get_authenticated_youtube_service()
    request = youtube.videos().list(
        part="snippet",
        id=video_id
    )
    response = request.execute()

    items = response.get("items", [])
    if items:
        return items[0]['snippet'].get('description', '')
    return ''



def get_transcript(video_id):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        return transcript
    except Exception as e:
        print(f"Transcript not available: {e}")
        return None


def send_to_openai(video_id, video_title, transcript, video_description):
    api_key = OPENAI_API_KEY
    if not api_key:
        print("❌ OPENAI_API_KEY environment variable not set")
        return None

    client = openai.OpenAI(api_key=api_key)

    transcript_text = "\n".join([f"[{int(entry['start'] // 60):02d}:{int(entry['start'] % 60):02d}] {entry['text']}" for entry in transcript])

    content = f"""
Video ID: {video_id}
Video Title: {video_title}

Description:
{video_description}

Transcript:
{transcript_text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": """You are an AI assistant helping analyze YouTube video transcripts from the channel Gameranx.

These videos often cover multiple games or gaming topics in a single episode — whether it’s a "Top 10", "Top 25 New Games", “10 Things You Need to Know”, or any other format.

Your task:
List each distinct game or topic segment that appears in the video, using this format:

mm:ss - [Game or Topic Title]

Where:
- mm:ss = The approximate timestamp (from the transcript or description) when that game/topic starts.
- The title should reflect the main subject or game being discussed in that section.

Use the following priority rules:
1. If the video **description already includes timestamps with clear titles**, extract and use those.
2. If the description has **only timestamps without titles or tittle like Number 1, Number 2**, try to infer the topic/game titles from the transcript starting, or close to those timestamps.
3. If no timestamps or useful data are found in the description, analyze the transcript normally to identify the segments.

Instructions:
- Focus only on actual game/topic segments — skip sponsor messages, intros, outros, and general chatter.
- Do NOT include full descriptions or summaries — just the timestamp and title.
- If no clear segments are found, respond with:
  No clear topic or game segments detected.

Example Output:
00:30 - Dragon’s Dogma 2
02:15 - Fallout: London
04:50 - GTA 6 Rumors
07:02 - Red Dead Redemption Modding Crackdown
09:45 - PS5 Slim Release
..."""
                },
                {
                    "role": "user",
                    "content": content
                }
            ],
            max_tokens=800,
            temperature=0.1
        )

        return response.choices[0].message.content

    except Exception as e:
        print(f"❌ Error sending to OpenAI: {e}")
        return None


def is_top_x_video(ai_response):
    if ai_response and "This is not a Top X video" in ai_response:
        return False
    return True


def parse_top_x_response(ai_response):
    if not ai_response:
        return []

    lines = ai_response.strip().split('\n')
    items = []

    for line in lines:
        line = line.strip()
        if line and '-' in line and not line.startswith('Example'):
            parts = line.split(' - ', 1)
            if len(parts) == 2:
                time_part = parts[0].strip()
                title_part = parts[1].strip()
                items.append({
                    "time": time_part,
                    "title": title_part
                })

    return items


def get_authenticated_youtube_service():
    creds = None

    # Load existing credentials if available
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # If no valid credentials, prompt login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the credentials for future use
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def post_youtube_comment(video_id, comment_text):
    youtube = get_authenticated_youtube_service()

    request_body = {
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {
                "snippet": {
                    "textOriginal": comment_text
                }
            }
        }
    }

    try:
        response = youtube.commentThreads().insert(
            part="snippet",
            body=request_body
        ).execute()

        print(f"✅ Comment posted: {response['snippet']['topLevelComment']['snippet']['textOriginal']}")
    except Exception as e:
        print(f"❌ Failed to post YouTube comment: {e}")


if __name__ == "__main__":
    channel_url = 'https://www.youtube.com/@gameranxTV/videos'

    try:
        latest_video_id, video_title = get_latest_video_id(channel_url)
        print(f"Latest Video ID: {latest_video_id}")
        print(f"Video Title: {video_title}")

        extraction_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        video_data = {
            "video_id": latest_video_id,
            "video_title": video_title,
            "channel_url": channel_url,
            "extraction_date": extraction_date
        }

        with open('video_id.json', 'w') as f:
            json.dump(video_data, f, indent=2)
        print("Video ID saved to video_id.json")

        transcript = get_transcript(latest_video_id)
        description = get_video_description(latest_video_id)


        if transcript:
            with open('transcript.json', 'w', encoding='utf-8') as f:
                json.dump(transcript, f, indent=2, ensure_ascii=False)
            print("Transcript saved to transcript.json")

            print("\n🤖 Analyzing for Top X content...")
            ai_response = send_to_openai(latest_video_id, video_title, transcript, description)

            if ai_response:
                print("\n📝 AI Analysis:")
                print("=" * 50)
                print(ai_response)
                print("=" * 50)

                if is_top_x_video(ai_response):
                    print("✅ This is a Top X video!")

                    top_x_items = parse_top_x_response(ai_response)

                    top_x_data = {
                        "video_id": latest_video_id,
                        "video_title": video_title,
                        "is_top_x": True,
                        "items": top_x_items,
                        "raw_ai_response": ai_response,
                        "timestamp": extraction_date
                    }

                    with open('top_x_analysis.json', 'w', encoding='utf-8') as f:
                        json.dump(top_x_data, f, indent=2, ensure_ascii=False)
                    print("Top X analysis saved to top_x_analysis.json")

                    # ✅ Format comment text
                    comment_text = "📋 Here's timestamps:\n\n"
                    for item in top_x_items:
                        comment_text += f"{item['time']} - {item['title']}\n"

                    # ✅ Enforce YouTube 1000 char limit
                    if len(comment_text) > 950:
                        comment_text = comment_text[:950] + "\n...(truncated for YouTube limit)"

                    # ✅ Post comment
                    print("\n🚀 Posting comment to YouTube...")
                    post_youtube_comment(latest_video_id, comment_text)

                else:
                    print("❌ This is not a Top X video. Stopping script.")
                    sys.exit(0)

            else:
                print("❌ OpenAI API call failed.")
                sys.exit(0)

        else:
            print("❌ No transcript available. Stopping script.")
            sys.exit(0)

    except Exception as e:
        print(f"An error occurred: {e}")
