import os
import json
import subprocess
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# -----------------------------
# CONFIG
# -----------------------------

SPOTIFY_CLIENT_ID = os.environ["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
SPOTIFY_REFRESH_TOKEN = os.environ["SPOTIFY_REFRESH_TOKEN"]

GOOGLE_CREDS_FILE = "service_account.json"
DRIVE_FOLDER_NAME = "SpotifyMusic"
STATE_FILE = "downloaded_songs.json"

# -----------------------------
# SPOTIFY AUTH
# -----------------------------

sp = Spotify(auth_manager=SpotifyOAuth(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET,
    redirect_uri="http://127.0.0.1:8888/callback",
    scope="user-library-read",
    open_browser=False,
    cache_path=None
))

sp.auth_manager.refresh_token = SPOTIFY_REFRESH_TOKEN
sp.auth_manager.refresh_access_token(SPOTIFY_REFRESH_TOKEN)

# -----------------------------
# GOOGLE DRIVE AUTH
# -----------------------------

creds = service_account.Credentials.from_service_account_file(
    GOOGLE_CREDS_FILE,
    scopes=["https://www.googleapis.com/auth/drive"]
)

drive = build("drive", "v3", credentials=creds)

# -----------------------------
# GET DRIVE FOLDER ID
# -----------------------------

def get_drive_folder_id():
    query = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder'"
    results = drive.files().list(q=query, fields="files(id, name)").execute()
    items = results.get("files", [])
    if not items:
        raise Exception("Drive folder not found")
    return items[0]["id"]

FOLDER_ID = get_drive_folder_id()

# -----------------------------
# GET LIKED SONGS
# -----------------------------

def get_liked_songs():
    songs = []
    offset = 0

    while True:
        results = sp.current_user_saved_tracks(limit=50, offset=offset)
        items = results["items"]
        if not items:
            break

        for item in items:
            track = item["track"]
            songs.append({
                "id": track["id"],
                "name": track["name"],
                "artist": track["artists"][0]["name"]
            })

        offset += 50

    return songs

# -----------------------------
# LOAD STATE
# -----------------------------

with open(STATE_FILE, "r") as f:
    state = json.load(f)

stored_tracks = {t["id"]: t for t in state["tracks"]}

# -----------------------------
# SYNC LOGIC
# -----------------------------

current_tracks = get_liked_songs()

current_ids = {t["id"] for t in current_tracks}
stored_ids = set(stored_tracks.keys())

new_ids = current_ids - stored_ids
removed_ids = stored_ids - current_ids

print(f"New songs: {len(new_ids)}")
print(f"Removed songs: {len(removed_ids)}")

# Reverse to download oldest first
current_tracks.reverse()

# -----------------------------
# DOWNLOAD NEW SONGS
# -----------------------------

for track in current_tracks:
    if track["id"] in new_ids:
        query = f"{track['name']} {track['artist']}"
        print("Downloading:", query)

        subprocess.run([
            "spotdl",
            "--format", "mp3",
            "--output", "{title} - {artist}.{output-ext}",
            query
        ])

        filename = f"{track['name']} - {track['artist']}.mp3"

        file_metadata = {
            "name": filename,
            "parents": [FOLDER_ID]
        }

        media = MediaFileUpload(filename, mimetype="audio/mpeg")
        drive.files().create(body=file_metadata, media_body=media).execute()

        os.remove(filename)

# -----------------------------
# DELETE REMOVED SONGS
# -----------------------------

for track_id in removed_ids:
    filename = stored_tracks[track_id]["filename"]

    query = f"name='{filename}' and '{FOLDER_ID}' in parents"
    results = drive.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])

    for file in files:
        drive.files().delete(fileId=file["id"]).execute()

# -----------------------------
# UPDATE STATE
# -----------------------------

new_state = []

for track in current_tracks[::-1]:  # restore original order
    filename = f"{track['name']} - {track['artist']}.mp3"
    new_state.append({
        "id": track["id"],
        "filename": filename
    })

with open(STATE_FILE, "w") as f:
    json.dump({"tracks": new_state}, f, indent=2)

print("Sync complete.")
