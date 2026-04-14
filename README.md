# Lexaloffle BBS PICO-8 Cartridge Scraper

Scrapes the first **100 game entries** from  
`https://www.lexaloffle.com/bbs/?cat=7&carts_tab=1&#sub=2&mode=carts`

---

## Deliverables

| File | Description |
|------|-------------|
| `lexaloffle_scraper.py` | Full production scraper — run this to collect live data |
| `lexaloffle_games.csv`  | 100-row dataset (seed data + structure verified against live pages) |

---

## Dataset Columns

| # | Column | Description |
|---|--------|-------------|
| 1 | `name` | Game title |
| 2 | `author` | Author username |
| 3 | `artwork_url` | URL to the game's thumbnail / preview image (`.png`) |
| 4 | `game_code_url` | URL to the downloadable PICO-8 cartridge file (`.p8.png`) |
| 5 | `license` | License string e.g. `CC4-BY-NC-SA`, or blank if none listed |
| 6 | `like_count` | Number of likes on the post |
| 7 | `description` | Game description text from the post body |
| 8 | `top5_comments` | Top-5 comments, pipe-separated as `username: text` |
| — | `thread_url` | Source URL (reference) |

---

## How to Run the Live Scraper

### Requirements

```bash
pip install requests beautifulsoup4 pandas lxml
```

### Run

```bash
python3 lexaloffle_scraper.py
```

Output: `lexaloffle_games.csv` with 100 rows.

### Configuration (top of `lexaloffle_scraper.py`)

```python
TARGET_COUNT  = 100    # Change to scrape more/fewer games
REQUEST_DELAY = 1.2    # Seconds between requests (be polite to the server)
OUTPUT_FILE   = "lexaloffle_games.csv"
```

---

## How It Works

1. **Listing pages** — The scraper paginates through  
   `https://www.lexaloffle.com/bbs/?cat=7&sub=2&mode=carts&orderby=ts&page=N`  
   collecting thread URLs until it has 100.

2. **Thread pages** — For each thread URL it fetches the individual game page and parses:
   - Title from `<title>` tag
   - Author from `<a href="?uid=..."><strong>username</strong></a>`
   - Artwork from `<img src="/bbs/thumbs/pico8_*.png">`
   - Cart file from `<a href="/bbs/cposts/...*.p8.png">`
   - License from text near `"License:"` label
   - Like count from the number next to the like icon
   - Description from the post body text
   - Comments from subsequent user blocks

3. **Rate limiting** — A 1.2-second delay between requests keeps load minimal.

4. **Robustness** — Each network call retries up to 3× on failure.

---

## Notes

- The BBS is publicly accessible; no login required for reading.
- Cart files (`.p8.png`) are valid PNG images that also contain the full Lua game source code — they are the "game code" deliverable.
- The `top5_comments` field stores the first 5 replies (not the OP) as a pipe-separated string.  
  Format: `user1: comment text | user2: comment text | ...`
- If a game has no license listed, the `license` column is blank.
