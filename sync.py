import os
import json
import subprocess
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# -----------------------------
# CONFIG
# -----------------------------

SPOTIFY_PLAYLIST_ID = "5nQKQAuiLpVriHVqadFyVt"
SPOTIFY_CLIENT_ID = os.environ["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]

GOOGLE_CREDS_FILE = "service_account.json"
DRIVE_FOLDER_NAME = "SpotifyMusic"
STATE_FILE = "downloaded_songs.json"

# -----------------------------
# SPOTIFY AUTH (Client Credentials)
# -----------------------------

auth_manager = SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
)

sp = Spotify(auth_manager=auth_manager)

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


FOLDER_ID ="1t6WlElAzNSwGuiZP113Fph_drdhRDtrJ"

# -----------------------------
# GET PLAYLIST TRACKS
# -----------------------------

def get_playlist_tracks(playlist_id):
    results = sp.playlist_items(playlist_id, additional_types=['track'])
    items = results["items"]
    tracks = []
    while results["next"]:
        results = sp.next(results)
        items.extend(results["items"])

    for item in items:
        track = item["track"]
        if track is None:
            continue
        tracks.append({
            "id": track["id"],
            "name": track["name"],
            "artist": track["artists"][0]["name"]
        })
    return tracks

# -----------------------------
# LOAD STATE
# -----------------------------

with open(STATE_FILE, "r") as f:
    state = json.load(f)

stored_tracks = {t["id"]: t for t in state["tracks"]}

# -----------------------------
# SYNC LOGIC
# -----------------------------

current_tracks = get_playlist_tracks(SPOTIFY_PLAYLIST_ID)

current_ids = {t["id"] for t in current_tracks}
stored_ids = set(stored_tracks.keys())

new_ids = current_ids - stored_ids
removed_ids = stored_ids - current_ids

print(f"New tracks: {len(new_ids)}")
print(f"Removed tracks: {len(removed_ids)}")

# Reverse to download oldest first
current_tracks.reverse()

# -----------------------------
# DOWNLOAD NEW TRACKS
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
# DELETE REMOVED TRACKS
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

for track in current_tracks[::-1]:  # restore playlist order
    filename = f"{track['name']} - {track['artist']}.mp3"
    new_state.append({
        "id": track["id"],
        "filename": filename
    })

with open(STATE_FILE, "w") as f:
    json.dump({"tracks": new_state}, f, indent=2)

print("Sync complete.")
