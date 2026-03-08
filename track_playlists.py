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

        # Scroll down to load all tracks (Tidal lazy-loads rows)
        previous_count = 0
        for _ in range(20):  # Max 20 scroll attempts
            current_count = await page.evaluate(
                'document.querySelectorAll(\'[data-test="tracklist-row"]\').length'
            )
            if current_count == previous_count:
                break  # No new rows loaded, we've reached the end
            previous_count = current_count
            await page.evaluate('window.scrollBy(0, 1000)')
            await asyncio.sleep(1)

        # Extract tracks
        tracks_data = await page.evaluate('''() => {
            const tracks = [];
            const rows = document.querySelectorAll('[data-test="tracklist-row"]');
            
            rows.forEach(row => {
                const dateAddedCell = row.querySelector('[data-test="track-row-date-added"]');
                if (!dateAddedCell) return;
                
                const dateText = dateAddedCell.innerText.trim();
                const lowerDateText = dateText.toLowerCase();
                
                if (lowerDateText === "today" || lowerDateText === "yesterday" || lowerDateText === "this week") {
                    const titleElement = row.querySelector('[data-test="table-row-title"] [data-test="table-cell-title"]');
                    const artistElement = row.querySelector('[data-test="track-row-artist"] a'); 
                    const albumElement = row.querySelector('[data-test="track-row-album"] a');
                    
                    tracks.push({
                        "Title": titleElement ? titleElement.innerText.trim() : "Unknown Title",
                        "Artist": artistElement ? artistElement.innerText.trim() : "Unknown Artist",
                        "Album": albumElement ? albumElement.innerText.trim() : "Unknown Album",
                        "Date Added": dateText
                    });
                }
            });
            return tracks;
        }''')
        
        print(f"  - Found {len(tracks_data)} matching tracks.")
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
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
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
        print("\nNo matching tracks found (Yesterday/This Week).")
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
