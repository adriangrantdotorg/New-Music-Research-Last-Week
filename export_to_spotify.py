import base64
import io
try:
    from PIL import Image as _PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
import csv
import glob
import os
import datetime
import time
import subprocess
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "playlist-modify-public playlist-modify-private ugc-image-upload"
# Support both .jpeg and .jpg
_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Playlist-Artwork")
ARTWORK_PATH = _base + ".jpeg" if os.path.exists(_base + ".jpeg") else _base + ".jpg"

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

def mac_notify(title, message):
    """Send a macOS notification via osascript."""
    script = f'display notification "{message}" with title "{title}"'
    subprocess.run(["osascript", "-e", script])

def spotify_call(fn, *args, **kwargs):
    """
    Calls a Spotify API function, automatically retrying after rate-limit (429) errors.
    Shows a Mac notification while waiting so you know what's happening.
    """
    while True:
        try:
            return fn(*args, **kwargs)
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", 30)) + 1
                msg = f"Waiting {retry_after}s for rate limit to reset..."
                print(f"\n  ⚠️  Rate limited — {msg}")
                mac_notify("🪁 DX — Spotify Rate Limit", msg)
                time.sleep(retry_after)
                print("  ↩️  Retrying...")
            else:
                raise

def compress_artwork(path, max_b64_bytes=180_000):
    """
    Returns a Base64-encoded JPEG string that fits within Spotify's image upload
    limit (~256KB base64 / ~190KB raw). Shrinks the image progressively if needed.
    Requires Pillow. Falls back to raw encoding if Pillow is unavailable.
    """
    if not _PIL_AVAILABLE:
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')

    img = _PILImage.open(path).convert('RGB')
    quality = 85
    scale = 1.0

    while True:
        w = int(img.width * scale)
        h = int(img.height * scale)
        resized = img.resize((w, h), _PILImage.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format='JPEG', quality=quality)
        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        if len(b64) <= max_b64_bytes or (quality <= 40 and scale <= 0.3):
            return b64
        # Try lowering quality first, then shrink dimensions
        if quality > 40:
            quality -= 10
        else:
            scale -= 0.1

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

    print(f"Processing: {csv_file}")
    
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
        user_id = spotify_call(sp.me)['id']
        print(f"Authenticated as: {user_id}")
    except Exception as e:
        print(f"Authentication failed: {e}")
        print("Please check your Client ID and Secret and `http://127.0.0.1:8888/callback` is in your App settings.")
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
    omitted = []  # Tracks that couldn't be confidently matched — saved to missed-tracks/

    def clean_query(t):
        return t.replace("ft.", "").replace("feat.", "").split("(")[0].strip()

    def pick_best_track(items):
        """Prefer the explicit version of a track. Falls back to the first result."""
        for item in items:
            if item.get('explicit', False):
                return item
        return items[0]

    def artist_matches(track_item, expected_artist):
        """
        Strict word-boundary artist check. Requires the expected artist name to match
        a whole word in the Spotify artist name (or vice versa), not just a substring.
        This prevents 'DRAM' matching 'DJ Drama' while still matching 'DRAM' exactly.
        Handles comma-separated artist strings (e.g. 'Artist A, Artist B').
        """
        import re
        # Split comma-separated artists from the scraped data
        expected_artists = [a.strip() for a in expected_artist.split(',')]
        for expected in expected_artists:
            expected_lower = expected.lower()
            for a in track_item['artists']:
                spotify_lower = a['name'].lower()
                # Exact match
                if expected_lower == spotify_lower:
                    return True
                # Word-boundary match: expected must appear as a whole word in spotify name,
                # or spotify name must appear as a whole word in expected
                pattern = r'\b' + re.escape(expected_lower) + r'\b'
                if re.search(pattern, spotify_lower):
                    return True
                pattern2 = r'\b' + re.escape(spotify_lower) + r'\b'
                if re.search(pattern2, expected_lower):
                    return True
        return False

    def filter_by_artist(items, expected_artist):
        return [t for t in items if artist_matches(t, expected_artist)]

    print("\nSearching Spotify for tracks...")
    for track in tracks_to_search:
        title = track.get('Title', '').strip()
        artist = track.get('Artist', '').strip()
        album = track.get('Album', '').strip()

        if not title or not artist:
            continue

        # Strategy 1: Title + Artist + Album
        res = spotify_call(sp.search, q=f"track:{clean_query(title)} artist:{clean_query(artist)} album:{clean_query(album)}", limit=5, type='track')
        items = filter_by_artist(res['tracks']['items'], artist)

        # Strategy 2: Title + Artist only
        if not items:
            res = spotify_call(sp.search, q=f"track:{clean_query(title)} artist:{clean_query(artist)}", limit=5, type='track')
            items = filter_by_artist(res['tracks']['items'], artist)

        # Strategy 3: Title only (broadest — catches cases where Tidal/Spotify artist names differ)
        if not items:
            res = spotify_call(sp.search, q=f"track:{clean_query(title)}", limit=10, type='track')
            items = filter_by_artist(res['tracks']['items'], artist)

        # No confident match — omit rather than risk a false track
        if items:
            best = pick_best_track(items)
            track_uris.append(best['uri'])
            explicit_tag = "EXPLICIT" if best.get('explicit', False) else "CLEAN"
            spotify_artists = ', '.join(a['name'] for a in best['artists'])
            print(f"  [FOUND/{explicit_tag}] {title} - {artist}  →  {best['name']} - {spotify_artists}")
        else:
            omitted.append({"Title": title, "Artist": artist, "Album": album,
                            "Source Playlist": track.get('Source Playlist', ''),
                            "Date Added": track.get('Date Added', '')})
            print(f"  [OMITTED] {title} - {artist}")

    # 5. Create Playlist
    now = datetime.datetime.now()
    current_date = now.strftime("%m-%d-%y")
    current_timestamp = now.strftime("%m-%d-%y__%I.%M.%S %p")
    playlist_name = f"🪁 DX {current_date}"
    
    print(f"\nCreating playlist: {playlist_name}")
    try:
        playlist = spotify_call(sp.user_playlist_create, user_id, playlist_name, public=False)
        playlist_id = playlist['id']
    except Exception as e:
        print(f"Error creating playlist: {e}")
        return

    # 6. Add Tracks first (artwork is separate — a 413 must never block track upload)
    if track_uris:
        try:
            # Add in chunks of 100 as per API limits
            for i in range(0, len(track_uris), 100):
                chunk = track_uris[i:i+100]
                spotify_call(sp.playlist_add_items, playlist_id, chunk)
            print(f"Successfully added {len(track_uris)} tracks to '{playlist_name}'.")
        except Exception as e:
            print(f"Error adding tracks: {e}")
    else:
        print("No tracks were found on Spotify to add.")

    print(f"SPOTIFY_URI:spotify:playlist:{playlist_id}")

    # 7. Upload artwork — isolated so failure never affects tracks
    if os.path.exists(ARTWORK_PATH):
        try:
            image_b64 = compress_artwork(ARTWORK_PATH)
            spotify_call(sp.playlist_upload_cover_image, playlist_id, image_b64)
            print("  🎨 Artwork uploaded.")
        except Exception as e:
            print(f"  ⚠️  Artwork upload failed: {e}")
    else:
        print(f"  ⚠️  Artwork not found at {ARTWORK_PATH} — skipping.")

    # 7. Save omitted tracks to missed-tracks/
    if omitted:
        os.makedirs("missed-tracks", exist_ok=True)
        missed_file = os.path.join("missed-tracks", f"MISSED {current_timestamp}.csv")
        keys = ["Title", "Artist", "Album", "Source Playlist", "Date Added"]
        with open(missed_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(omitted)
        print(f"\n⚠️  {len(omitted)} track(s) omitted (no confident Spotify match):")
        for t in omitted:
            print(f"   - {t['Title']} - {t['Artist']}")
        print(f"   Saved to {missed_file}")
    else:
        print("\n✅ All tracks matched successfully — nothing omitted.")

if __name__ == "__main__":
    main()
