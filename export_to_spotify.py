import csv
import glob
import os
import datetime
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
# Configuration
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "playlist-modify-public playlist-modify-private"

def get_latest_csv():
    """Finds the most recently created SCRAPED csv file."""
    files = glob.glob("scraped-files/SCRAPED *.csv")
    if not files:
        return None
    # Sort by modification time (or name since it has timestamp)
    # Using os.path.getmtime just to be safe about "latest" creation
    latest_file = max(files, key=os.path.getmtime)
    return latest_file

def get_credentials():
    """Prompts user for credentials if not found in env."""
    global CLIENT_ID, CLIENT_SECRET
    
    if not CLIENT_ID:
        print("\n--- Spotify Credentials Required ---")
        print("You can find these in your Spotify Developer Dashboard.")
        CLIENT_ID = input("Enter your Spotify Client ID: ").strip()
        
    if not CLIENT_SECRET:
        if not CLIENT_ID: # If user just hit enter above, maybe they set them now?
             CLIENT_ID = input("Enter your Spotify Client ID: ").strip()
        CLIENT_SECRET = input("Enter your Spotify Client Secret: ").strip()
        
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Error: Client ID and Client Secret are required so we can talk to Spotify.")
        return False
    return True

def main():
    # 1. basic setup
    import sys
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    else:
        print("Looking for latest scraped CSV...")
        csv_file = get_latest_csv()
        
    if not csv_file:
        print("Error: No CSV file provided or found.")
        return

    print(f"Propcessing: {csv_file}")
    
    # 2. Authenticate
    if not get_credentials():
        return

    try:
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=SCOPE,
            open_browser=True
        ))
        user_id = sp.me()['id']
        print(f"Authenticated as: {user_id}")
    except Exception as e:
        print(f"Authentication failed: {e}")
        print("Please check your Client ID and Secret and `http://localhost:8888/callback` is in your App settings.")
        return

    # 3. Read Tracks
    tracks_to_search = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                tracks_to_search.append(row)
    except Exception as e:
        print(f"Error reading CSV {csv_file}: {e}")
        return
            
    if not tracks_to_search:
        print("No tracks found in CSV.")
        return
        
    print(f"Loaded {len(tracks_to_search)} tracks from CSV.")

    # 4. Search and Collect URIs
    track_uris = []
    not_found = []

    # Helper to simplify search queries
    def clean_query(t):
        return t.replace("ft.", "").replace("feat.", "").split("(")[0].strip()

    def pick_best_track(items):
        """Prefer the explicit version of a track. Falls back to the first result."""
        for item in items:
            if item.get('explicit', False):
                return item
        return items[0]  # fallback: no explicit version found
    
    print("\nSearching Spotify for tracks...")
    for track in tracks_to_search:
        title = track.get('Title', '').strip()
        artist = track.get('Artist', '').strip()
        album = track.get('Album', '').strip()
        
        if not title or not artist:
            continue

        # Strategy 1: Title + Artist + Album (fetch up to 5 to find explicit version)
        query = f"track:{clean_query(title)} artist:{clean_query(artist)} album:{clean_query(album)}"
        results = sp.search(q=query, limit=5, type='track')
        
        # Strategy 2: Title + Artist only
        if not results['tracks']['items']:
            query = f"track:{clean_query(title)} artist:{clean_query(artist)}"
            results = sp.search(q=query, limit=5, type='track')
             
        if results['tracks']['items']:
            best = pick_best_track(results['tracks']['items'])
            uri = best['uri']
            is_explicit = best.get('explicit', False)
            explicit_tag = "EXPLICIT" if is_explicit else "CLEAN (no explicit version found)"
            track_uris.append(uri)
            print(f"  [FOUND/{explicit_tag}] {title} - {artist}")
        else:
            not_found.append(f"{title} - {artist}")
            print(f"  [MISSING] {title} - {artist}")

    # 5. Create Playlist
    current_date = datetime.datetime.now().strftime("%m-%d-%y")
    playlist_name = f"🪁 DX {current_date}"
    
    print(f"\nCreating playlist: {playlist_name}")
    try:
        playlist = sp.user_playlist_create(user_id, playlist_name, public=False)
        playlist_id = playlist['id']
        
        # 6. Add Tracks
        if track_uris:
            # Add in chunks of 100 as per API limits
            for i in range(0, len(track_uris), 100):
                chunk = track_uris[i:i+100]
                sp.playlist_add_items(playlist_id, chunk)
            print(f"Successfully added {len(track_uris)} tracks to '{playlist_name}'.")
        else:
            print("No tracks were found on Spotify to add.")

        print(f"SPOTIFY_URI:spotify:playlist:{playlist_id}")
            
        if not_found:
            print(f"\nCould not find {len(not_found)} tracks:")
            for t in not_found:
                print(f" - {t}")
                
    except Exception as e:
        print(f"Error creating/filling playlist: {e}")

if __name__ == "__main__":
    main()
