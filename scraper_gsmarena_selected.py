import csv
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin

import requests

BASE = "https://m.gsmarena.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

BRANDS = [
    {"name": "Apple", "url": "https://m.gsmarena.com/apple-phones-48.php"},
    {"name": "Google", "url": "https://m.gsmarena.com/google-phones-107.php"},
    {"name": "Honor", "url": "https://m.gsmarena.com/honor-phones-121.php"},
    {"name": "Infinix", "url": "https://m.gsmarena.com/infinix-phones-119.php"},
    {"name": "Motorola", "url": "https://m.gsmarena.com/motorola-phones-4.php"},
    {"name": "Samsung", "url": "https://m.gsmarena.com/samsung-phones-9.php"},
    {"name": "Xiaomi", "url": "https://m.gsmarena.com/xiaomi-phones-80.php"},
]

RE_LAST_PAGE = re.compile(r'id="last-button"[^>]*href="([^"]+)"', re.I)
RE_PHONE_CARD = re.compile(
    r'<li>\s*<a\s+href="([^"]+\.php)">\s*<img[^>]*src="([^"]+)"[^>]*>\s*<strong>([^<]+)</strong>\s*</a>\s*</li>',
    re.I,
)
RE_BRAND_MAIN = re.compile(r'/([a-z0-9_+\-]+)-phones-(\d+)\.php$', re.I)
RE_PHONE_ID = re.compile(r'-(\d+)\.php$', re.I)
RE_H1 = re.compile(r'<h1[^>]*>(.*?)</h1>', re.I | re.S)
RE_DATA_SPEC = re.compile(r'data-spec="([^"]+)"[^>]*>(.*?)</(?:td|span)>', re.I | re.S)
RE_TTL_NFO = re.compile(r'<td\s+class="ttl"[^>]*>(.*?)</td>\s*<td\s+class="nfo"[^>]*>(.*?)</td>', re.I | re.S)
RE_TAGS = re.compile(r'<[^>]+>')
RE_WS = re.compile(r'\s+')
EXCLUDED_KEYWORDS = (
    " tab",
    "tablet",
    " pad",
    "watch",
    "buds",
    "band",
    "pixel c",
    "ipad",
)


def clean_html_text(s: str) -> str:
    s = re.sub(r'<br\s*/?>', ' | ', s, flags=re.I)
    s = RE_TAGS.sub(' ', s)
    s = unescape(s)
    s = RE_WS.sub(' ', s).strip()
    return s


def fetch(session: requests.Session, url: str, retries: int = 3, timeout: int = 20) -> str:
    delay = 0.8
    for attempt in range(retries + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.text
            if r.status_code in (408, 429, 500, 502, 503, 504):
                raise requests.RequestException(f"status={r.status_code}")
            return ""
        except Exception:
            if attempt == retries:
                return ""
            time.sleep(delay)
            delay *= 2
    return ""


def build_brand_pages(brand_url: str, html: str) -> list[str]:
    m = RE_LAST_PAGE.search(html)
    if not m:
        return [brand_url]

    last_href = m.group(1)
    if last_href == "#":
        return [brand_url]

    mm = re.search(r'-p(\d+)\.php$', last_href)
    if not mm:
        return [brand_url]

    max_page = int(mm.group(1))
    main_match = RE_BRAND_MAIN.search(brand_url)
    if not main_match:
        return [brand_url]

    slug = main_match.group(1)
    brand_id = main_match.group(2)

    pages = [brand_url]
    for p in range(2, max_page + 1):
        pages.append(f"{BASE}{slug}-phones-f-{brand_id}-0-p{p}.php")
    return pages


def parse_listing(brand_url: str, page_url: str, html: str) -> list[dict]:
    out = []
    main_match = RE_BRAND_MAIN.search(brand_url)
    brand_slug = main_match.group(1) if main_match else ""
    brand_id = main_match.group(2) if main_match else ""

    for href, img, name in RE_PHONE_CARD.findall(html):
        phone_url = urljoin(BASE, href)
        img_url = urljoin(BASE, img)
        id_match = RE_PHONE_ID.search(phone_url)
        phone_id = id_match.group(1) if id_match else ""
        out.append(
            {
                "brand_slug": brand_slug,
                "brand_id": brand_id,
                "listing_page_url": page_url,
                "phone_url": phone_url,
                "image_url": img_url,
                "phone_name_listing": clean_html_text(name),
                "phone_id": phone_id,
            }
        )
    return out


def parse_phone_specs(html: str) -> tuple[str, dict]:
    h1 = RE_H1.search(html)
    title = clean_html_text(h1.group(1)) if h1 else ""

    specs = {}
    for key, val_html in RE_DATA_SPEC.findall(html):
        val = clean_html_text(val_html)
        if val:
            specs[key] = val

    for ttl_html, nfo_html in RE_TTL_NFO.findall(html):
        key = clean_html_text(ttl_html).lower()
        val = clean_html_text(nfo_html)
        if key and val and key not in specs:
            specs[key] = val

    return title, specs


def is_non_phone_candidate(name: str, specs: dict) -> bool:
    n = f" {name.lower()} "
    if any(k in n for k in EXCLUDED_KEYWORDS):
        return True
    body = specs.get("body", "")
    if body and "tablet" in body.lower():
        return True
    return False


def main() -> None:
    os.makedirs("dataset", exist_ok=True)
    out_csv = os.path.join("dataset", "gsmarena_selected_brands.csv")

    session = requests.Session()
    brand_urls = [b["url"] for b in BRANDS]

    brand_first_pages = {}
    for brand_url in brand_urls:
        html = fetch(session, brand_url)
        if html:
            brand_first_pages[brand_url] = html

    all_listing_urls = []
    for brand_url, html in brand_first_pages.items():
        all_listing_urls.extend(build_brand_pages(brand_url, html))

    listing_html_map = {}
    with ThreadPoolExecutor(max_workers=20) as ex:
        fut_map = {ex.submit(fetch, session, u): u for u in all_listing_urls}
        for fut in as_completed(fut_map):
            u = fut_map[fut]
            listing_html_map[u] = fut.result() or ""

    listing_rows = []
    for page_url, html in listing_html_map.items():
        if not html:
            continue
        for brand_url in brand_urls:
            if RE_BRAND_MAIN.search(brand_url):
                slug = RE_BRAND_MAIN.search(brand_url).group(1)
                if f"/{slug}-phones-" in page_url or f"/{slug}-phones-f-" in page_url:
                    listing_rows.extend(parse_listing(brand_url, page_url, html))
                    break

    unique_models = {}
    for row in listing_rows:
        key = row["phone_id"] or row["phone_url"]
        if key not in unique_models:
            unique_models[key] = row

    phone_urls = [r["phone_url"] for r in unique_models.values()]

    phone_html_map = {}
    with ThreadPoolExecutor(max_workers=24) as ex:
        fut_map = {ex.submit(fetch, session, u): u for u in phone_urls}
        for fut in as_completed(fut_map):
            u = fut_map[fut]
            phone_html_map[u] = fut.result() or ""

    scraped_at = datetime.now(timezone.utc).isoformat()
    rows_out = []
    removed_non_phone = 0
    for model in unique_models.values():
        html = phone_html_map.get(model["phone_url"], "")
        title, specs = ("", {})
        if html:
            title, specs = parse_phone_specs(html)
        final_name = title or model["phone_name_listing"]
        if is_non_phone_candidate(final_name, specs):
            removed_non_phone += 1
            continue

        rows_out.append(
            {
                "brand_slug": model["brand_slug"],
                "brand_id": model["brand_id"],
                "phone_id": model["phone_id"],
                "phone_name": final_name,
                "phone_url": model["phone_url"],
                "image_url": model["image_url"],
                "listing_page_url": model["listing_page_url"],
                "scraped_at_utc": scraped_at,
                "specs_json": json.dumps(specs, ensure_ascii=False, separators=(",", ":")),
            }
        )

    rows_out.sort(key=lambda r: (r["brand_slug"], r["phone_name"]))

    fieldnames = [
        "brand_slug",
        "brand_id",
        "phone_id",
        "phone_name",
        "phone_url",
        "image_url",
        "listing_page_url",
        "scraped_at_utc",
        "specs_json",
    ]
    try:
        with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_out)
        written_file = out_csv
    except PermissionError:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fallback = os.path.join("dataset", f"gsmarena_selected_brands_{ts}.csv")
        with open(fallback, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_out)
        written_file = fallback

    fields_to_check = ["phone_id", "phone_name", "phone_url", "image_url", "specs_json"]
    blank_stats = {}
    total = len(rows_out) if rows_out else 1
    for field in fields_to_check:
        blanks = sum(1 for r in rows_out if not (r.get(field) or "").strip())
        blank_stats[field] = {
            "blanks": blanks,
            "pct": round((blanks / total) * 100, 2),
        }

    print(f"DONE rows={len(rows_out)} file={written_file}")
    print(f"FILTERED_NON_PHONE={removed_non_phone}")
    print("BLANK_CHECK_START")
    for f in fields_to_check:
        s = blank_stats[f]
        print(f"{f}: blanks={s['blanks']} pct={s['pct']}%")
    print("BLANK_CHECK_END")


if __name__ == "__main__":
    main()
