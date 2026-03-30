import asyncio
import csv
import json
import os
import datetime
import subprocess
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

# Generate output filename with timestamp
# Format: scraped-files/SCRAPED MM-dd-yy__h.mm.ss a.csv
os.makedirs("scraped-files", exist_ok=True)
current_time = datetime.datetime.now().strftime("%m-%d-%y__%I.%M.%S %p")
output_file = os.path.join("scraped-files", f"SCRAPED {current_time}.csv")

def trigger_km_macro(uuid):
    """Triggers a Keyboard Maestro macro by its UUID using osascript."""
    script = f'tell application "Keyboard Maestro Engine" to do script "{uuid}"'
    try:
        subprocess.run(["osascript", "-e", script], check=True)
        print(f"Successfully triggered KM macro: {uuid}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to trigger KM macro: {e}")

def load_playlists(filename="playlists.json"):
    if not os.path.exists(filename):
        print(f"Error: {filename} not found.")
        return []
    with open(filename, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            return []

async def extract_visible_tracks(page):
    """Extract tracks currently visible in the virtualized DOM."""
    return await page.evaluate('''() => {
        const tracks = [];
        const rows = document.querySelectorAll('[data-test="tracklist-row"]');
        
        rows.forEach(row => {
            const dateAddedCell = row.querySelector('[data-test="track-row-date-added"]');
            if (!dateAddedCell) return;
            
            const dateText = dateAddedCell.innerText.trim();
            const lowerDateText = dateText.toLowerCase();
            
            // Collect ALL tracks — we filter by date below but also need
            // to know when we've scrolled past the recent section.
            const titleElement = row.querySelector('[data-test="table-row-title"] [data-test="table-cell-title"]');
            const artistElements = row.querySelectorAll('[data-test="track-row-artist"] a'); 
            const albumElement = row.querySelector('[data-test="track-row-album"] a');
            const artistNames = Array.from(artistElements).map(a => a.innerText.trim());
            
            tracks.push({
                "Title": titleElement ? titleElement.innerText.trim() : "Unknown Title",
                "Artist": artistNames.length > 0 ? artistNames.join(', ') : "Unknown Artist",
                "Album": albumElement ? albumElement.innerText.trim() : "Unknown Album",
                "Date Added": dateText
            });
        });
        return tracks;
    }''')

async def scrape_playlist(page, playlist):
    print(f"Scraping: {playlist['name']} ({playlist['url']})")
    try:
        await page.goto(playlist['url'])
        # Wait for the tracklist to load
        try:
           await page.wait_for_selector('[data-test="tracklist-row"]', timeout=10000)
        except:
           print(f"  - Timeout waiting for tracklist on {playlist['name']}")
           return []

        # Give the DOM a moment to fully render after initial load
        await asyncio.sleep(1)

        # Tidal uses a virtualized list: only ~16-18 rows exist in the DOM
        # at any given time. We must scroll the #main container (not window)
        # and collect tracks at each scroll position, deduplicating by key.
        seen_keys = set()
        all_tracks = []
        no_new_tracks_count = 0

        for scroll_attempt in range(50):  # Max 50 scroll attempts (handles 60+ track playlists)
            # Extract whatever tracks are currently in the DOM
            visible = await extract_visible_tracks(page)

            new_this_round = 0
            for t in visible:
                key = (t["Title"], t["Artist"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_tracks.append(t)
                    new_this_round += 1

            if new_this_round == 0:
                no_new_tracks_count += 1
                if no_new_tracks_count >= 3:
                    break  # Three consecutive scrolls with no new tracks — we're at the end
            else:
                no_new_tracks_count = 0

            # Scroll the #main container (Tidal's actual scrollable element)
            await page.evaluate('document.getElementById("main").scrollBy(0, 600)')
            await asyncio.sleep(0.8)

        # Filter to only tracks added last week
        recent_keywords = {"last week"}
        tracks_data = [
            t for t in all_tracks
            if t["Date Added"].strip().lower() in recent_keywords
        ]

        print(f"  - Scanned {len(all_tracks)} total tracks, {len(tracks_data)} are recent.")
        # Add source playlist to each track
        for track in tracks_data:
            track["Source Playlist"] = playlist['name']
            
        return tracks_data

    except Exception as e:
        print(f"  - Error scraping {playlist['name']}: {e}")
        return []

async def main():
    playlists = load_playlists()
    if not playlists:
        return

    all_tracks = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()

        for playlist in playlists:
            tracks = await scrape_playlist(page, playlist)
            all_tracks.extend(tracks)
        
        await browser.close()

    if all_tracks:
        print(f"\nTotal matches found before deduping: {len(all_tracks)}")
        
        # Remove duplicates based on Artist, Album, Title
        unique_tracks = []
        seen_tracks = set()
        
        for track in all_tracks:
            # Create a unique key for the track
            track_key = (track['Artist'], track['Album'], track['Title'])
            
            if track_key not in seen_tracks:
                seen_tracks.add(track_key)
                unique_tracks.append(track)
                
        print(f"Total unique matches found: {len(unique_tracks)}")

        # Write to CSV
        keys = ["Title", "Artist", "Album", "Source Playlist", "Date Added"]
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            dict_writer = csv.DictWriter(f, fieldnames=keys)
            dict_writer.writeheader()
            dict_writer.writerows(unique_tracks)
        print(f"Saved to {output_file}")
        
        # Trigger Spotify Export
        print("\n--- Starting Spotify Export ---")
        try:
            result = subprocess.run(
                ["python3", "export_to_spotify.py", output_file],
                check=True,
                capture_output=True,
                text=True
            )
            # Print all output so SPOTIFY_URI: tag is visible to AppleScript
            print(result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Error running Spotify export: {e}")
        except Exception as e:
            print(f"An error occurred: {e}")
            
    else:
        print("\nNo matching tracks found (Last Week).")
        # Create empty CSV with headers just in case
        keys = ["Title", "Artist", "Album", "Source Playlist", "Date Added"]
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            dict_writer = csv.DictWriter(f, fieldnames=keys)
            dict_writer.writeheader()
        print(f"Created empty {output_file}")

    # Trigger Keyboard Maestro macro (optional — only runs if KM_MACRO_UUID is set in .env)
    km_uuid = os.getenv("KM_MACRO_UUID")
    if km_uuid:
        trigger_km_macro(km_uuid)
    else:
        print("KM_MACRO_UUID not set — skipping Keyboard Maestro trigger.")

if __name__ == "__main__":
    asyncio.run(main())
