import csv
import glob
import json
import os
import re
import subprocess
import sys
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
RE_YEAR = re.compile(r'(20\d{2})')
RE_PAGINATION_OF = re.compile(r'>\s*\d+\s+of\s+(\d+)\s*<', re.I)
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
MIN_LAUNCH_YEAR_INCLUSIVE = 2022


def clean_html_text(s: str) -> str:
    s = re.sub(r'<br\s*/?>', ' | ', s, flags=re.I)
    s = RE_TAGS.sub(' ', s)
    s = unescape(s)
    s = RE_WS.sub(' ', s).strip()
    return s


def fetch_with_meta(session: requests.Session, url: str, retries: int = 3, timeout: int = 20) -> dict:
    delay = 0.8
    attempts = 0
    last_error = ""
    last_status = None
    for attempt in range(retries + 1):
        attempts = attempt + 1
        try:
            r = session.get(url, headers=HEADERS, timeout=timeout)
            last_status = r.status_code
            if r.status_code == 200:
                return {
                    "ok": True,
                    "url": url,
                    "status": r.status_code,
                    "attempts": attempts,
                    "error": "",
                    "html": r.text,
                }
            if r.status_code in (408, 429, 500, 502, 503, 504):
                raise requests.RequestException(f"status={r.status_code}")
            return {
                "ok": False,
                "url": url,
                "status": r.status_code,
                "attempts": attempts,
                "error": f"status={r.status_code}",
                "html": "",
            }
        except Exception as exc:
            last_error = str(exc)
            if attempt == retries:
                return {
                    "ok": False,
                    "url": url,
                    "status": last_status,
                    "attempts": attempts,
                    "error": last_error or "request_exception",
                    "html": "",
                }
            time.sleep(delay)
            delay *= 2

    return {
        "ok": False,
        "url": url,
        "status": last_status,
        "attempts": attempts,
        "error": last_error or "unknown",
        "html": "",
    }


def build_brand_pages(brand_url: str, html: str) -> list[str]:
    # GSMArena may render attributes in different order:
    # <a href="...p14.php" id="last-button"> or <a id="last-button" href="...p14.php">
    m = re.search(r'<a[^>]*id="last-button"[^>]*href="([^"]+)"', html, re.I)
    if not m:
        m = re.search(r'<a[^>]*href="([^"]+)"[^>]*id="last-button"', html, re.I)

    max_page = 1
    if m:
        last_href = m.group(1)
        mm = re.search(r'-p(\d+)\.php$', last_href or "")
        if mm:
            max_page = int(mm.group(1))

    # Fallback from visible page counter, e.g. "4 of 14"
    if max_page == 1:
        pm = RE_PAGINATION_OF.search(html)
        if pm:
            max_page = int(pm.group(1))

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


def extract_launch_year(specs: dict) -> int | None:
    raw = " | ".join(
        [
            str(specs.get("year", "")),
            str(specs.get("announced", "")),
            str(specs.get("released-hl", "")),
            str(specs.get("status", "")),
        ]
    )
    m = RE_YEAR.search(raw)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def retry_failed_phone_fetches(session: requests.Session, failed_urls: list[str], log_events: list[dict]) -> dict:
    recovered = 0
    still_failed = []
    recovered_html = {}

    if not failed_urls:
        return {
            "recovered": 0,
            "still_failed": [],
            "html_map": {},
        }

    with ThreadPoolExecutor(max_workers=8) as ex:
        fut_map = {
            ex.submit(fetch_with_meta, session, u, retries=4, timeout=30): u
            for u in failed_urls
        }
        for fut in as_completed(fut_map):
            url = fut_map[fut]
            res = fut.result()
            if res.get("ok") and res.get("html"):
                recovered += 1
                recovered_html[url] = res.get("html", "")
                log_events.append(
                    {
                        "event": "phone_fetch_retry_recovered",
                        "url": url,
                        "status": res.get("status"),
                        "attempts": res.get("attempts"),
                        "error": "",
                    }
                )
            else:
                still_failed.append(url)
                log_events.append(
                    {
                        "event": "phone_fetch_retry_failed",
                        "url": url,
                        "status": res.get("status"),
                        "attempts": res.get("attempts"),
                        "error": res.get("error"),
                    }
                )

    return {
        "recovered": recovered,
        "still_failed": still_failed,
        "html_map": recovered_html,
    }


def latest_normalized_csv() -> str:
    candidates = sorted(glob.glob(os.path.join("dataset", "gsmarena_selected_brands_normalized_*.csv")))
    if not candidates:
        return ""
    return max(candidates, key=os.path.getmtime)


def build_2022plus_from_normalized(src_csv: str) -> tuple[str, int]:
    out_csv = os.path.join("dataset", "gsmarena_selected_brands_normalized_2022plus.csv")
    with open(src_csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
            f.write("")
        return out_csv, 0

    filtered = [
        r
        for r in rows
        if (r.get("announced_year") or "").isdigit()
        and int(r["announced_year"]) >= MIN_LAUNCH_YEAR_INCLUSIVE
    ]
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(filtered)
    return out_csv, len(filtered)


def main() -> None:
    os.makedirs("dataset", exist_ok=True)
    os.makedirs(os.path.join("dataset", "logs"), exist_ok=True)
    out_csv = os.path.join("dataset", "gsmarena_selected_brands.csv")
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join("dataset", "logs", f"scrape_run_{run_ts}.jsonl")
    log_events = []

    session = requests.Session()
    brand_urls = [b["url"] for b in BRANDS]

    brand_first_pages = {}
    for brand_url in brand_urls:
        res = fetch_with_meta(session, brand_url)
        if res["ok"] and res["html"]:
            brand_first_pages[brand_url] = res["html"]
        else:
            log_events.append(
                {
                    "event": "brand_first_page_failed",
                    "url": brand_url,
                    "status": res.get("status"),
                    "attempts": res.get("attempts"),
                    "error": res.get("error"),
                }
            )

    all_listing_urls = []
    for brand_url, html in brand_first_pages.items():
        all_listing_urls.extend(build_brand_pages(brand_url, html))

    listing_html_map = {}
    listing_failed_urls = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        fut_map = {ex.submit(fetch_with_meta, session, u): u for u in all_listing_urls}
        for fut in as_completed(fut_map):
            u = fut_map[fut]
            res = fut.result()
            listing_html_map[u] = res.get("html", "") if res.get("ok") else ""
            if not res.get("ok"):
                listing_failed_urls.append(u)
                log_events.append(
                    {
                        "event": "listing_fetch_failed",
                        "url": u,
                        "status": res.get("status"),
                        "attempts": res.get("attempts"),
                        "error": res.get("error"),
                    }
                )

    listing_rows = []
    for page_url, html in listing_html_map.items():
        if not html:
            continue
        for brand_url in brand_urls:
            m = RE_BRAND_MAIN.search(brand_url)
            if m:
                slug = m.group(1)
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
    phone_failed_urls = []
    with ThreadPoolExecutor(max_workers=24) as ex:
        fut_map = {ex.submit(fetch_with_meta, session, u): u for u in phone_urls}
        for fut in as_completed(fut_map):
            u = fut_map[fut]
            res = fut.result()
            phone_html_map[u] = res.get("html", "") if res.get("ok") else ""
            if not res.get("ok"):
                phone_failed_urls.append(u)
                log_events.append(
                    {
                        "event": "phone_fetch_failed",
                        "url": u,
                        "status": res.get("status"),
                        "attempts": res.get("attempts"),
                        "error": res.get("error"),
                    }
                )

    retry_result = retry_failed_phone_fetches(session, phone_failed_urls, log_events)
    phone_html_map.update(retry_result["html_map"])
    phone_failed_urls = retry_result["still_failed"]

    scraped_at = datetime.now(timezone.utc).isoformat()
    rows_out = []
    removed_non_phone = 0
    removed_by_launch_year = 0
    removed_missing_launch_year = 0
    for model in unique_models.values():
        html = phone_html_map.get(model["phone_url"], "")
        title, specs = ("", {})
        if html:
            title, specs = parse_phone_specs(html)
        final_name = title or model["phone_name_listing"]
        if is_non_phone_candidate(final_name, specs):
            removed_non_phone += 1
            continue

        launch_year = extract_launch_year(specs)
        if launch_year is None:
            removed_missing_launch_year += 1
            log_events.append(
                {
                    "event": "filtered_missing_launch_year",
                    "url": model["phone_url"],
                    "phone_name": final_name,
                }
            )
            continue
        if launch_year < MIN_LAUNCH_YEAR_INCLUSIVE:
            removed_by_launch_year += 1
            log_events.append(
                {
                    "event": "filtered_by_launch_year",
                    "url": model["phone_url"],
                    "phone_name": final_name,
                    "launch_year": launch_year,
                    "threshold_inclusive": MIN_LAUNCH_YEAR_INCLUSIVE,
                }
            )
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

    summary = {
        "event": "run_summary",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "brands_requested": len(brand_urls),
        "brand_first_pages_ok": len(brand_first_pages),
        "listing_urls_expected": len(all_listing_urls),
        "listing_urls_ok": len(all_listing_urls) - len(listing_failed_urls),
        "listing_urls_failed": len(listing_failed_urls),
        "phone_urls_expected": len(phone_urls),
        "phone_urls_ok": len(phone_urls) - len(phone_failed_urls),
        "phone_urls_failed": len(phone_failed_urls),
        "phone_urls_recovered_on_retry": retry_result["recovered"],
        "rows_out": len(rows_out),
        "filtered_non_phone": removed_non_phone,
        "filtered_by_launch_year": removed_by_launch_year,
        "filtered_missing_launch_year": removed_missing_launch_year,
        "launch_year_threshold_inclusive": MIN_LAUNCH_YEAR_INCLUSIVE,
        "output_csv": written_file,
        "log_file": log_path,
    }
    log_events.append(summary)

    with open(log_path, "w", encoding="utf-8") as lf:
        for ev in log_events:
            lf.write(json.dumps(ev, ensure_ascii=False) + "\n")

    print(f"DONE rows={len(rows_out)} file={written_file}")
    print(f"FILTERED_NON_PHONE={removed_non_phone}")
    print("RUN_SUMMARY_START")
    for k in [
        "brands_requested",
        "brand_first_pages_ok",
        "listing_urls_expected",
        "listing_urls_ok",
        "listing_urls_failed",
        "phone_urls_expected",
        "phone_urls_ok",
        "phone_urls_failed",
        "phone_urls_recovered_on_retry",
        "rows_out",
        "filtered_non_phone",
        "filtered_by_launch_year",
        "filtered_missing_launch_year",
        "launch_year_threshold_inclusive",
    ]:
        print(f"{k}: {summary[k]}")
    print(f"log_file: {log_path}")
    print("RUN_SUMMARY_END")

    print("BLANK_CHECK_START")
    for f in fields_to_check:
        s = blank_stats[f]
        print(f"{f}: blanks={s['blanks']} pct={s['pct']}%")
    print("BLANK_CHECK_END")


    # One-command pipeline: also normalize and build 2022+ CSV.
    norm = subprocess.run([sys.executable, "normalize_specs_csv.py"], capture_output=True, text=True)
    print("NORMALIZE_START")
    if norm.stdout.strip():
        print(norm.stdout.strip())
    if norm.returncode != 0:
        if norm.stderr.strip():
            print(norm.stderr.strip())
        print("NORMALIZE_END")
        raise SystemExit(norm.returncode)

    latest_norm = latest_normalized_csv()
    if latest_norm:
        plus2022_csv, rows_2022plus = build_2022plus_from_normalized(latest_norm)
        print(f"normalized_csv: {latest_norm}")
        print(f"normalized_2022plus_csv: {plus2022_csv}")
        print(f"normalized_2022plus_rows: {rows_2022plus}")
    print("NORMALIZE_END")


if __name__ == "__main__":
    main()
