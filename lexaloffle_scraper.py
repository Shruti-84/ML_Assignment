import csv
import re
import time
import logging
from dataclasses import dataclass, field, fields
from typing import Optional

import requests
from bs4 import BeautifulSoup



BASE_URL      = "https://www.lexaloffle.com"
LISTING_URL   = f"{BASE_URL}/bbs/?cat=7&sub=2&mode=carts&orderby=ts"
OUTPUT_FILE   = "lexaloffle_games.csv"
TARGET_COUNT  = 100          
REQUEST_DELAY = 1.2          
PAGE_SIZE     = 30          

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; LexaloffleResearchBot/1.0; "
        "+https://github.com/your-repo)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)



@dataclass
class GameEntry:
    name:           str = ""
    author:         str = ""
    artwork_url:    str = ""
    game_code_url:  str = ""
    license:        str = ""
    like_count:     int = 0
    description:    str = ""
    top5_comments:  str = ""   
    thread_url:     str = ""  



session = requests.Session()
session.headers.update(HEADERS)


def get_soup(url: str, retries: int = 3) -> Optional[BeautifulSoup]:
    """Fetch a URL and return a BeautifulSoup object, with retries."""
    for attempt in range(1, retries + 1):
        try:
            log.debug(f"GET {url}  (attempt {attempt})")
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except requests.RequestException as exc:
            log.warning(f"Request failed ({attempt}/{retries}): {exc}")
            if attempt < retries:
                time.sleep(REQUEST_DELAY * attempt)
    log.error(f"Giving up on {url}")
    return None


def polite_sleep():
    time.sleep(REQUEST_DELAY)



def get_thread_links_from_listing_page(page: int = 1) -> list[str]:
    """
    Return thread URLs found on a listing page.
    Lexaloffle uses ?page=N (1-based).
    """
    url = LISTING_URL if page == 1 else f"{LISTING_URL}&page={page}"
    soup = get_soup(url)
    if not soup:
        return []

    links = []
    
    for a in soup.find_all("a", href=re.compile(r"\?tid=\d+")):
        href = a["href"]
        full = href if href.startswith("http") else BASE_URL + "/" + href.lstrip("/")
        
        if full not in links:
            links.append(full)

    log.info(f"Listing page {page}: found {len(links)} thread links")
    return links


def collect_thread_urls(target: int) -> list[str]:
    """Accumulate thread URLs across listing pages until we have enough."""
    all_urls: list[str] = []
    page = 1
    seen: set[str] = set()

    while len(all_urls) < target:
        polite_sleep()
        new_links = get_thread_links_from_listing_page(page)
        if not new_links:
            log.warning(f"No links found on page {page}; stopping pagination.")
            break
        for link in new_links:
            if link not in seen:
                seen.add(link)
                all_urls.append(link)
        if len(new_links) < PAGE_SIZE:
            log.info("Fewer links than page size — likely last page.")
            break
        page += 1

    log.info(f"Total unique thread URLs collected: {len(all_urls)}")
    return all_urls[:target]



def _extract_name(soup: BeautifulSoup) -> str:
    """Extract game title from the <title> tag or first h1."""
    # Page <title> is usually "Game Title" directly
    title_tag = soup.find("title")
    if title_tag and title_tag.text.strip():
        return title_tag.text.strip()
    h1 = soup.find("h1")
    return h1.text.strip() if h1 else ""


def _extract_author(soup: BeautifulSoup) -> str:
    """Author name appears inside a <strong> inside a link to /bbs/?uid=..."""
    link = soup.find("a", href=re.compile(r"\?uid=\d+"))
    if link:
        strong = link.find("strong")
        if strong:
            return strong.text.strip()
        return link.text.strip()
    return ""


def _extract_artwork_url(soup: BeautifulSoup) -> str:
    """Thumbnail URL: /bbs/thumbs/pico8_<slug>.png"""
    img = soup.find("img", src=re.compile(r"/bbs/thumbs/pico8_"))
    if img:
        src = img["src"]
        return src if src.startswith("http") else BASE_URL + src
    return ""


def _extract_game_code_url(soup: BeautifulSoup) -> str:
    """Cart file URL: /bbs/cposts/.../xxx.p8.png  (the downloadable cartridge)"""
    
    link = soup.find("a", href=re.compile(r"\.p8\.png$"))
    if link:
        href = link["href"]
        return href if href.startswith("http") else BASE_URL + href
    
    img = soup.find("img", src=re.compile(r"\.p8\.png$"))
    if img:
        src = img["src"]
        return src if src.startswith("http") else BASE_URL + src
    return ""


def _extract_license(soup: BeautifulSoup) -> str:
    """License text, e.g. 'CC4-BY-NC-SA', appears near 'License:' text."""
    
    for tag in soup.find_all(string=re.compile(r"License\s*:", re.I)):
        parent = tag.parent
        
        for a in parent.find_all("a"):
            text = a.text.strip()
            if text:
                return text
        
        raw = parent.get_text()
        m = re.search(r"License\s*:\s*([^\n|]+)", raw, re.I)
        if m:
            return m.group(1).strip()
    return ""


def _extract_like_count(soup: BeautifulSoup) -> int:
    """
    Like count: a small number adjacent to the heart/like icon.
    The BBS renders it as plain text next to set_like icon images.
    Strategy: find all occurrences of standalone digit strings near like icons.
    """
    
    for img in soup.find_all("img", src=re.compile(r"set_like")):
        
        for sib in img.next_siblings:
            text = str(sib).strip()
            if re.match(r"^\d+$", text):
                return int(text)
           
            if hasattr(sib, "text"):
                t = sib.text.strip()
                if re.match(r"^\d+$", t):
                    return int(t)
  
    all_nums = re.findall(r"(?<!\d)(\d{1,5})(?!\d)", soup.get_text())
    
    for n in all_nums:
        val = int(n)
        if 0 <= val <= 9999:
            return val
    return 0


def _extract_description(soup: BeautifulSoup) -> str:
    """
    Description: the text body of the first post (after the cart widget).
    We look for the paragraph/div that follows the cart embed block.
    """
    
    post_divs = soup.find_all("div", class_=re.compile(r"post|bpost|message", re.I))
    if post_divs:
     
        for div in post_divs:
            text = div.get_text(separator=" ", strip=True)
            if len(text) > 30:
                return _clean_text(text)[:1000]

   
    full_text = soup.get_text(separator="\n")
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]


    desc_lines = []
    capture = False
    for line in lines:
        if re.search(r"Cart\s*#|Code\s*▽|Embed\s*▽|License:", line):
            capture = True
            continue
        if capture:
            # Stop at tags/comments section markers
            if re.search(r"^\[|\bPlease log in\b|^More Cartridges|^Generated", line):
                break
            if len(line) > 10:
                desc_lines.append(line)
        if len(desc_lines) >= 8:
            break

    description = " ".join(desc_lines).strip()
    return _clean_text(description)[:1000]


def _extract_top5_comments(soup: BeautifulSoup) -> str:
    """
    Extract top-5 comments (by position, i.e. first 5 replies after OP).
    Returns a pipe-separated string of "username: comment_text".
    """
    comments = []

    
    user_links = soup.find_all("a", href=re.compile(r"\?uid=\d+"))

   
    seen_users_text = set()
    comment_idx = 0

    for ul in user_links:
        username = ul.find("strong")
        username = username.text.strip() if username else ul.text.strip()
        if not username:
            continue

        
        container = ul.find_parent(["tr", "div", "li", "section", "article"])
        if not container:
            container = ul.parent

        
        raw = container.get_text(separator=" ", strip=True)
        
        text = raw.replace(username, "", 1).strip()
        text = _clean_text(text)

        
        if len(text) < 15:
            continue
        fingerprint = (username, text[:60])
        if fingerprint in seen_users_text:
            continue
        seen_users_text.add(fingerprint)

        comments.append(f"{username}: {text[:300]}")
        comment_idx += 1
        if comment_idx >= 6:  
            break

  
    reply_comments = comments[1:6]
    return " | ".join(reply_comments)


def _clean_text(text: str) -> str:
    """Remove excess whitespace and non-printable characters."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[^\x20-\x7E\n]", "", text)  # Keep printable ASCII + newlines
    return text.strip()


def scrape_game_thread(thread_url: str) -> Optional[GameEntry]:
    """Scrape a single game thread page and return a GameEntry."""
    soup = get_soup(thread_url)
    if not soup:
        return None

    entry = GameEntry()
    entry.thread_url   = thread_url
    entry.name         = _extract_name(soup)
    entry.author       = _extract_author(soup)
    entry.artwork_url  = _extract_artwork_url(soup)
    entry.game_code_url = _extract_game_code_url(soup)
    entry.license      = _extract_license(soup)
    entry.like_count   = _extract_like_count(soup)
    entry.description  = _extract_description(soup)
    entry.top5_comments = _extract_top5_comments(soup)

    log.info(
        f"  ✓ '{entry.name}' by {entry.author} | "
        f"likes={entry.like_count} | license='{entry.license}'"
    )
    return entry



FIELDNAMES = [
    "name",
    "author",
    "artwork_url",
    "game_code_url",
    "license",
    "like_count",
    "description",
    "top5_comments",
    "thread_url",
]


def save_to_csv(entries: list[GameEntry], filename: str):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for e in entries:
            writer.writerow({fn: getattr(e, fn) for fn in FIELDNAMES})
    log.info(f"Saved {len(entries)} entries to '{filename}'")



def main():
    log.info("=" * 60)
    log.info("Lexaloffle BBS PICO-8 Cartridge Scraper")
    log.info(f"Target: {TARGET_COUNT} games → {OUTPUT_FILE}")
    log.info("=" * 60)

    # Step 1: Collect thread URLs from listing pages
    log.info("Step 1/2 — Collecting thread URLs from listing pages...")
    thread_urls = collect_thread_urls(TARGET_COUNT)

    if not thread_urls:
        log.error("No thread URLs found. Check network / URL structure.")
        return

    log.info(f"Collected {len(thread_urls)} thread URLs.")

    # Step 2: Scrape each thread
    log.info("Step 2/2 — Scraping individual game threads...")
    entries: list[GameEntry] = []
    for i, url in enumerate(thread_urls, 1):
        log.info(f"[{i}/{len(thread_urls)}] {url}")
        polite_sleep()
        entry = scrape_game_thread(url)
        if entry:
            entries.append(entry)

    log.info(f"Successfully scraped {len(entries)} games.")

    # Step 3: Save
    save_to_csv(entries, OUTPUT_FILE)
    log.info("Done! ✅")


if __name__ == "__main__":
    main()
