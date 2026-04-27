import csv
import glob
import json
import os
import re
from datetime import datetime, timezone

DATASET_DIR = 'dataset'

BASE_COLUMNS = [
    'brand_slug','brand_id','phone_id','phone_name','phone_url','image_url','listing_page_url','scraped_at_utc'
]

NORM_COLUMNS = [
    'announced_year','status','os','chipset','cpu','gpu',
    'display_size_in','display_resolution','display_refresh_hz',
    'battery_mah','charging_w',
    'ram_options_gb','storage_options_gb',
    'main_camera_mp','selfie_camera_mp',
    'has_5g','has_nfc','has_esim','has_sd_slot',
    'price_text','price_currency','price_usd'
]

RE_NUM = re.compile(r'(\d+(?:\.\d+)?)')
RE_BATTERY = re.compile(r'(\d{3,5})\s*mAh', re.I)
RE_WATT = re.compile(r'(\d+(?:\.\d+)?)\s*W', re.I)
RE_INCH = re.compile(r'(\d+(?:\.\d+)?)\s*(?:inches|\")', re.I)
RE_HZ = re.compile(r'(\d{2,3})\s*Hz', re.I)
RE_RES = re.compile(r'(\d{3,4}\s*x\s*\d{3,4})', re.I)
RE_MP = re.compile(r'(\d+(?:\.\d+)?)\s*MP', re.I)
RE_RAM_GB = re.compile(r'(\d+(?:\.\d+)?)\s*GB\s*RAM', re.I)
RE_STORAGE_GB = re.compile(r'(\d+(?:\.\d+)?)\s*GB', re.I)
RE_STORAGE_TB = re.compile(r'(\d+(?:\.\d+)?)\s*TB', re.I)
RE_YEAR = re.compile(r'(20\d{2})')
RE_PRICE_NUM = re.compile(r'(\d[\d,\.]*)')

FX_TO_USD = {
    'USD': 1.0,
    'EUR': 1.08,
    'GBP': 1.27,
    'INR': 0.012,
}


def to_float_str(v):
    if v is None:
        return ''
    try:
        f = float(v)
        if f.is_integer():
            return str(int(f))
        return str(round(f, 2))
    except Exception:
        return ''


def parse_unique_sorted(values):
    if not values:
        return ''
    uniq = sorted(set(values), key=lambda x: float(x))
    return '|'.join(to_float_str(v) for v in uniq)


def get(specs, *keys):
    for k in keys:
        v = specs.get(k)
        if v:
            return v
    return ''


def extract_ram_storage(specs):
    text = ' | '.join(str(v) for v in specs.values())
    ram = [m.group(1) for m in RE_RAM_GB.finditer(text)]

    storage = [m.group(1) for m in RE_STORAGE_GB.finditer(get(specs,'internalmemory','internal','storage-hl'))]
    tb = [str(float(m.group(1))*1024) for m in RE_STORAGE_TB.finditer(get(specs,'internalmemory','internal','storage-hl'))]
    storage.extend(tb)
    return parse_unique_sorted(ram), parse_unique_sorted(storage)


def extract_first_float(pattern, text):
    if not text:
        return ''
    m = pattern.search(text)
    if not m:
        return ''
    return to_float_str(m.group(1))


def parse_price_to_usd(price_text):
    txt = (price_text or '').strip()
    if not txt:
        return '', ''

    lower = txt.lower()
    currency = 'USD'
    if '€' in txt or 'eur' in lower:
        currency = 'EUR'
    elif '£' in txt or 'gbp' in lower:
        currency = 'GBP'
    elif '₹' in txt or 'inr' in lower or 'rs' in lower:
        currency = 'INR'
    elif '$' in txt or 'usd' in lower:
        currency = 'USD'

    nm = RE_PRICE_NUM.search(txt.replace(' ', ''))
    if not nm:
        return currency, ''

    raw = nm.group(1)
    if ',' in raw and '.' in raw:
        raw = raw.replace(',', '')
    elif ',' in raw:
        raw = raw.replace(',', '')

    try:
        amount = float(raw)
    except Exception:
        return currency, ''

    usd = amount * FX_TO_USD.get(currency, 1.0)
    return currency, to_float_str(usd)


def normalize_row(row):
    specs = json.loads(row.get('specs_json') or '{}')

    announced_raw = get(specs, 'year', 'announced', 'released-hl')
    announced_year = ''
    ym = RE_YEAR.search(announced_raw or '')
    if ym:
        announced_year = ym.group(1)

    os_text = get(specs, 'os', 'os-hl')
    chipset = get(specs, 'chipset', 'chipset-hl')
    cpu = get(specs, 'cpu')
    gpu = get(specs, 'gpu')
    status = get(specs, 'status')

    disp_size = extract_first_float(RE_INCH, get(specs, 'displaysize', 'displaysize-hl', 'size'))
    disp_res = ''
    res_text = get(specs, 'displayresolution', 'displayres-hl', 'resolution')
    rm = RE_RES.search(res_text or '')
    if rm:
        disp_res = rm.group(1).replace(' ', '')
    hz = extract_first_float(RE_HZ, ' | '.join([get(specs,'displaytype','type'), get(specs,'displayother')]))

    batt_mah = extract_first_float(RE_BATTERY, ' | '.join([get(specs,'batdescription1','battery','batsize-hl')]))
    charging_w = extract_first_float(RE_WATT, ' | '.join([get(specs,'charging','battype-hl')]))

    ram_gb, storage_gb = extract_ram_storage(specs)

    main_cam = extract_first_float(RE_MP, get(specs,'cam1modules','camera','single','dual','triple','quad','camerapixels-hl'))
    selfie_cam = extract_first_float(RE_MP, get(specs,'cam2modules'))

    net_text = ' | '.join([get(specs,'nettech','technology','speed'), get(specs,'net5g','5g bands')]).lower()
    has_5g = '1' if '5g' in net_text else '0'

    nfc_text = get(specs, 'nfc').lower()
    has_nfc = '0' if (not nfc_text or nfc_text in {'no','n/a'}) else '1'

    sim_text = get(specs, 'sim').lower()
    has_esim = '1' if 'esim' in sim_text else '0'

    sd_text = get(specs, 'memoryslot', 'card slot').lower()
    has_sd_slot = '0' if (not sd_text or sd_text == 'no') else '1'

    price_text = get(specs,'price')
    price_currency, price_usd = parse_price_to_usd(price_text)

    out = {k: row.get(k,'') for k in BASE_COLUMNS}
    out.update({
        'announced_year': announced_year,
        'status': status,
        'os': os_text,
        'chipset': chipset,
        'cpu': cpu,
        'gpu': gpu,
        'display_size_in': disp_size,
        'display_resolution': disp_res,
        'display_refresh_hz': hz,
        'battery_mah': batt_mah,
        'charging_w': charging_w,
        'ram_options_gb': ram_gb,
        'storage_options_gb': storage_gb,
        'main_camera_mp': main_cam,
        'selfie_camera_mp': selfie_cam,
        'has_5g': has_5g,
        'has_nfc': has_nfc,
        'has_esim': has_esim,
        'has_sd_slot': has_sd_slot,
        'price_text': price_text,
        'price_currency': price_currency,
        'price_usd': price_usd,
    })
    return out


def latest_source_csv():
    candidates = sorted(
        p for p in glob.glob(os.path.join(DATASET_DIR, 'gsmarena_selected_brands_*.csv'))
        if 'normalized' not in os.path.basename(p).lower()
    )
    if not candidates:
        raise FileNotFoundError('No source CSV found')
    return max(candidates, key=os.path.getmtime)


def main():
    src = latest_source_csv()
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    out = os.path.join(DATASET_DIR, f'gsmarena_selected_brands_normalized_{ts}.csv')

    with open(src, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows = [normalize_row(r) for r in reader]

    fieldnames = BASE_COLUMNS + NORM_COLUMNS
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # quick null report
    total = len(rows) if rows else 1
    report_cols = ['display_size_in','battery_mah','ram_options_gb','storage_options_gb','main_camera_mp','has_5g','has_nfc']
    print(f'SOURCE={src}')
    print(f'OUTPUT={out}')
    print(f'ROWS={len(rows)}')
    print('NULL_REPORT_START')
    for c in report_cols:
        b = sum(1 for r in rows if not (r.get(c,'').strip()))
        print(f'{c}: blanks={b} pct={round((b/total)*100,2)}%')
    print('NULL_REPORT_END')


if __name__ == '__main__':
    main()
