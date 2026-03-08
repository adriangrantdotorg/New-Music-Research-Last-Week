# 🪁 Generate Spotify Playlist featuring the latest Hip-Hop & R&B tracks

Scrapes new tracks from curated Tidal playlists and exports them directly into a new Spotify playlist.

---

## ▶️ How to Run

```bash
python3 track_playlists.py
```

That's it. The script handles everything automatically from start to finish.

---

## ✅ What to Expect

1. **Tidal is scraped** — every playlist in `playlists.json` is visited and checked for tracks added **Today**, **Yesterday**, or **This Week**
2. **A CSV is saved** — a timestamped file is created in the `scraped-files` folder, e.g.:
   ```
   scraped-files/SCRAPED 02-20-26__10.15.00 PM.csv
   ```
3. **A Spotify playlist is created** — a new private playlist is added to your Spotify account named:
   ```
   🪁 DX 02-20-26
   ```
4. **All found tracks are added** to that playlist automatically
5. **The playlist opens in the Spotify desktop app** automatically once it's been created
6. **A Keyboard Maestro macro is triggered** _(optional)_ — if `KM_MACRO_UUID` is set in `.env`, the macro is fired via `osascript` at the very end

> If a track exists on multiple Tidal playlists, duplicates are removed before export.

---

## 📋 Playlists Tracked

| Playlist                 | URL                                                                     |
| :----------------------- | :---------------------------------------------------------------------- |
| Rap Bars & Melodies      | [Open](https://tidal.com/playlist/90bb6aed-d267-4766-952e-1360c1e5c6ed) |
| Thoro Hip-Hop            | [Open](https://tidal.com/playlist/34c543c9-bb74-4b79-91a8-feb6d815f43c) |
| Women of Hip-Hop         | [Open](https://tidal.com/playlist/6be1934e-3c52-4401-9001-676d05409083) |
| Hip-Hop & R&B Club Music | [Open](https://tidal.com/playlist/640fb9c7-14c3-4e99-b1c4-c74114fd776e) |
| New Midwest              | [Open](https://tidal.com/playlist/1b9478ed-c2ed-43db-8391-71fac43238fb) |
| Hip-Hop: RISING          | [Open](https://tidal.com/playlist/5eec3912-d862-4159-9a4c-a393b826a011) |
| Viral Hype               | [Open](https://tidal.com/playlist/ed9f3bf6-2149-4f18-b664-a56ff27ea130) |
| New West Coast           | [Open](https://tidal.com/playlist/496b977b-dd14-4ce7-9cb3-bfbd3e950229) |
| New South                | [Open](https://tidal.com/playlist/117dd55c-2c0b-453f-87c7-8b453286e92d) |
| Drill Hype               | [Open](https://tidal.com/playlist/6896171c-2b4a-47bf-b044-ae3886a521d7) |
| New East Coast           | [Open](https://tidal.com/playlist/7da79d8b-32d5-4d0e-be93-5021761805c4) |

To add or remove playlists, edit `playlists.json`.

---

## ⚙️ Setup

### Requirements

```bash
pip install playwright spotipy python-dotenv
playwright install chromium
```

### Environment Variables

Create a `.env` file in the project root:

```
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
KM_MACRO_UUID=your_macro_uuid   # optional — omit to skip the KM trigger
```

Get these from the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
Make sure `http://127.0.0.1:8888/callback` is added as a Redirect URI in your app settings.

---

## 🍎 Run from Anywhere (AppleScript)

You can trigger the full pipeline from anywhere on your Mac — via **Script Editor**, **Raycast**, **Alfred**, **Keyboard Maestro**,or any AppleScript-compatible launcher.

Save the following as a `.scpt` file in Script Editor:

```applescript
set projectPath to "your path here"

-- Run the Python script and capture output
set scriptOutput to do shell script "cd " & quoted form of projectPath & " && python3 track_playlists.py"

-- Find the Spotify URI from the output
set spotifyURI to ""
repeat with outputLine in paragraphs of scriptOutput
    if outputLine starts with "SPOTIFY_URI:" then
        set spotifyURI to text 13 thru -1 of outputLine
        exit repeat
    end if
end repeat

-- Open the playlist in the Spotify desktop app
if spotifyURI is not "" then
    tell application "Spotify"
        activate
        open location spotifyURI
    end tell
else
    display dialog "Playlist was created but could not find the Spotify URI in the script output." buttons {"OK"} default button "OK"
end if
```

**How it works:**

1. Runs `track_playlists.py`, which scrapes Tidal and calls `export_to_spotify.py`
2. `export_to_spotify.py` prints a `SPOTIFY_URI:` tag after the playlist is created
3. AppleScript captures that URI and opens the playlist directly in the **Spotify desktop app**
