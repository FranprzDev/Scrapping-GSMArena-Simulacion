# GSMArena Scraping (Marcas Seleccionadas)

## Objetivo
Scrapear modelos de celulares desde GSMArena Mobile para estas marcas:
- Apple
- Google
- Honor
- Infinix
- Motorola
- Samsung
- Xiaomi

Y exportar un CSV en `dataset/` con specs por equipo.

## Fuentes por marca
- Apple: https://m.gsmarena.com/apple-phones-48.php
- Google: https://m.gsmarena.com/google-phones-107.php
- Honor: https://m.gsmarena.com/honor-phones-121.php
- Infinix: https://m.gsmarena.com/infinix-phones-119.php
- Motorola: https://m.gsmarena.com/motorola-phones-4.php
- Samsung: https://m.gsmarena.com/samsung-phones-9.php
- Xiaomi: https://m.gsmarena.com/xiaomi-phones-80.php

## Script
- Archivo: `scraper_gsmarena_selected.py`
- Output: `dataset/gsmarena_selected_brands_YYYYMMDD_HHMMSS.csv`
- Normalizador: `normalize_specs_csv.py`
- Output normalizado: `dataset/gsmarena_selected_brands_normalized_YYYYMMDD_HHMMSS.csv`

## Enfoque técnico
1. Descubre paginación por marca desde la primera página (`id="last-button"`).
2. Descarga listados en paralelo (`ThreadPoolExecutor`).
3. Extrae modelos desde cards HTML (`li > a > img + strong`).
4. Deduplica por `phone_id`.
5. Descarga fichas de modelos en paralelo.
6. Extrae specs desde `data-spec` y fallback `ttl/nfo`.
7. Exporta CSV en UTF-8 con BOM (`utf-8-sig`).

## Filtro "solo celulares"
Se excluyen explícitamente no-celulares por nombre/specs:
- `watch`
- `tab`
- `tablet`
- ` pad`
- `band`
- `buds`
- `pixel c`
- `ipad`

También se descartan equipos cuyo `body` contiene `tablet`.

## Cómo correr
```bash
python scraper_gsmarena_selected.py
```

## Estructura del CSV
Columnas:
- `brand_slug`
- `brand_id`
- `phone_id`
- `phone_name`
- `phone_url`
- `image_url`
- `listing_page_url`
- `scraped_at_utc`
- `specs_json`

## Estructura del CSV normalizado
Columnas agregadas para comparador:
- `announced_year`
- `status`
- `os`
- `chipset`
- `cpu`
- `gpu`
- `display_size_in`
- `display_resolution`
- `display_refresh_hz`
- `battery_mah`
- `charging_w`
- `ram_options_gb`
- `storage_options_gb`
- `main_camera_mp`
- `selfie_camera_mp`
- `has_5g`
- `has_nfc`
- `has_esim`
- `has_sd_slot`
- `price_text`
- `price_currency`
- `price_usd`

## Resultado de la corrida final
Archivo generado:
- `dataset/gsmarena_selected_brands_20260427_052934.csv`
- `dataset/gsmarena_selected_brands_normalized_20260427_061843.csv`

Métricas:
- Filas finales: `267`
- Excluidos por filtro no-celular: `73`
- Campos vacíos:
  - `phone_id`: `0.0%`
  - `phone_name`: `0.0%`
  - `phone_url`: `0.0%`
  - `image_url`: `0.0%`
  - `specs_json`: `0.0%`

Distribución por marca:
- apple: 21
- google: 34
- honor: 42
- infinix: 50
- motorola: 44
- samsung: 40
- xiaomi: 36

## Validación de calidad aplicada
Post-proceso se verifica que no haya filas con señales de no-celular en:
- `phone_name`
- `specs_json`

Estado validación final:
- `flagged_rows = 0` (sin tablets/watches/bands detectados).

Validación CSV normalizado (blanks):
- `display_size_in`: `0.0%`
- `battery_mah`: `0.0%`
- `ram_options_gb`: `0.0%`
- `storage_options_gb`: `0.0%`
- `main_camera_mp`: `0.0%`
- `has_5g`: `0.0%`
- `has_nfc`: `0.0%`

## Nota operativa
Si el archivo de salida está abierto (por ejemplo en Excel), el script crea automáticamente un archivo nuevo con timestamp para evitar errores de permisos.
