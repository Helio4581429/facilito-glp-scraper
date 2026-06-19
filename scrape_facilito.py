"""
Extractor diario de precios GLP envasado de Facilito (Osinergmin).
Alcance: TODOS los establecimientos en LURIN para balones de 15 Kg y 45 Kg.

Bypass reCAPTCHA: renderiza con Playwright (Chromium real). reCAPTCHA v3
emite el token automaticamente al cargar la pagina.

Salida: append a precios.csv en el mismo repo.
Power BI lee el CSV desde la URL publica de GitHub.
"""

import os
import sys
import csv
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# -----------------------------------------------------------------------------
# Configuracion
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("facilito")

FACILITO_URL = (
    "https://www.facilito.gob.pe/facilito/pages/facilito/"
    "buscadorEnvasadoGLP.jsp?tipoEnvasado=PE"
)

# Codigos capturados del DOM real
COD_DEPARTAMENTO = "150000"  # LIMA
COD_PROVINCIA    = "150100"  # LIMA
COD_DISTRITO     = "150119"  # LURIN

# Productos a iterar
PRODUCTOS = [
    {"codigo": "53", "nombre": "15 Kg"},
    {"codigo": "54", "nombre": "45 Kg"},
]

# Ruta del CSV de salida (relativa al repo)
CSV_PATH = Path("precios.csv")

# Cabeceras del CSV
CSV_HEADERS = [
    "fecha_extraccion",
    "hora_extraccion",
    "distrito",
    "marca",
    "establecimiento",
    "direccion",
    "telefono",
    "precio",
    "producto",
    "fuente",
]


# -----------------------------------------------------------------------------
# 1. Scraping
# -----------------------------------------------------------------------------
def scrape_lurin_todos_establecimientos() -> list[dict]:
    todas_filas: list[dict] = []
    now_lima = datetime.now(ZoneInfo("America/Lima"))
    fecha_str = now_lima.strftime("%Y-%m-%d")
    hora_str  = now_lima.strftime("%H:%M:%S")

    log.info("Iniciando navegador Playwright (headless)...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="es-PE",
        )
        page = context.new_page()

        try:
            log.info(f"Cargando: {FACILITO_URL}")
            page.goto(FACILITO_URL, wait_until="networkidle", timeout=60000)

            log.info(f"Departamento LIMA ({COD_DEPARTAMENTO})...")
            page.evaluate(f"makeAction({COD_DEPARTAMENTO})")
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            log.info(f"Provincia LIMA ({COD_PROVINCIA})...")
            page.evaluate(f"""
                document.querySelector('select[name="provincia"]').value = '{COD_PROVINCIA}';
                cambiarProvincia();
            """)
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(2000)

            log.info(f"Distrito LURIN ({COD_DISTRITO})...")
            page.evaluate(f"""
                document.querySelector('select[name="distrito"]').value = '{COD_DISTRITO}';
                cambiarDistrito();
            """)
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(2000)

            for prod in PRODUCTOS:
                log.info(f"Producto {prod['nombre']} ({prod['codigo']})...")
                page.evaluate(f"""
                    document.querySelector('select[name="producto"]').value = '{prod['codigo']}';
                    cambiarProducto();
                """)
                page.wait_for_load_state("networkidle", timeout=60000)
                page.wait_for_timeout(2000)

                filas_producto = page.evaluate("""
                    () => {
                        const out = [];
                        const rows = document.querySelectorAll('#tblPreciosAGranelGlp tbody tr');
                        for (const r of rows) {
                            const th = r.querySelector('th');
                            const cells = r.querySelectorAll('td');
                            if (th && cells.length >= 5) {
                                out.push({
                                    distrito:        th.innerText.trim(),
                                    marca:           cells[0].innerText.trim(),
                                    establecimiento: cells[1].innerText.trim(),
                                    direccion:       cells[2].innerText.trim(),
                                    telefono:        cells[3].innerText.trim(),
                                    precio:          cells[4].innerText.trim()
                                });
                            }
                        }
                        return out;
                    }
                """)

                if not filas_producto:
                    log.warning(f"No se encontraron filas para {prod['nombre']} en LURIN")
                    continue

                for f in filas_producto:
                    precio_clean = f["precio"].replace(",", "").strip()
                    try:
                        precio_num = float(precio_clean)
                    except ValueError:
                        log.warning(f"Precio no parseable: '{f['precio']}' - omitido")
                        continue

                    todas_filas.append({
                        "fecha_extraccion": fecha_str,
                        "hora_extraccion":  hora_str,
                        "distrito":         f["distrito"],
                        "marca":            f["marca"],
                        "establecimiento":  f["establecimiento"],
                        "direccion":        f["direccion"],
                        "telefono":         f["telefono"],
                        "precio":           precio_num,
                        "producto":         prod["nombre"],
                        "fuente":           "Facilito Osinergmin",
                    })

                log.info(f"  -> {len(filas_producto)} establecimientos para {prod['nombre']}")

            log.info(f"Total filas extraidas: {len(todas_filas)}")
            if not todas_filas:
                log.warning("0 filas: guardando captura y HTML para diagnostico")
                try:
                    page.screenshot(path="error_debug.png", full_page=True)
                    Path("page_debug.html").write_text(page.content(), encoding="utf-8")
                except Exception as e:
                    log.error(f"No se pudo guardar diagnostico: {e}")
            return todas_filas

        except PWTimeout as e:
            log.error(f"Timeout durante scraping: {e}")
            try:
                page.screenshot(path="error_debug.png", full_page=True)
            except Exception:
                pass
            raise
        finally:
            context.close()
            browser.close()


# -----------------------------------------------------------------------------
# 2. Append a CSV
# -----------------------------------------------------------------------------
def append_to_csv(filas: list[dict]):
    if not filas:
        log.warning("Sin filas para agregar - skip CSV")
        return

    file_exists = CSV_PATH.exists()

    # Si no existe, crear con headers
    if not file_exists:
        log.info(f"Creando archivo nuevo: {CSV_PATH}")
        with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()

    # Append filas
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        for row in filas:
            writer.writerow(row)

    log.info(f"Agregadas {len(filas)} filas a {CSV_PATH}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    try:
        filas = scrape_lurin_todos_establecimientos()
        if not filas:
            log.error("Cero filas extraidas - abortando sin escribir")
            sys.exit(1)

        append_to_csv(filas)

        n_costa = sum(1 for f in filas if "COSTA" in f["marca"].upper()
                      or "COSTA" in f["establecimiento"].upper())
        log.info(f"OK - {len(filas)} filas, {n_costa} de Costa Gas")

    except Exception as e:
        log.error(f"Ejecucion fallo: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
