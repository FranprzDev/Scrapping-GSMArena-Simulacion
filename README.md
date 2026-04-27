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

## Script
- Archivo: `scraper_gsmarena_selected.py`
- Output: `dataset/gsmarena_selected_brands_YYYYMMDD_HHMMSS.csv`

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

## Resultado de la corrida final
Archivo generado:
- `dataset/gsmarena_selected_brands_20260427_052934.csv`

Métricas:
- Filas finales: `269`
- Excluidos por filtro no-celular: `71`
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
- xiaomi: 38

## Validación de calidad aplicada
Post-proceso se verifica que no haya filas con señales de no-celular en:
- `phone_name`
- `specs_json`

Estado validación final:
- `flagged_rows = 0` (sin tablets/watches/bands detectados).

## Nota operativa
Si el archivo de salida está abierto (por ejemplo en Excel), el script crea automáticamente un archivo nuevo con timestamp para evitar errores de permisos.
