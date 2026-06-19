"""
Extractor diario de precios GLP Automotor (a granel) de Facilito (Osinergmin).
Alcance: TODOS los gasocentros en LURIN que venden GLP - Granel.

Bypass reCAPTCHA: renderiza con Playwright (Chromium real). reCAPTCHA v3
emite el token automaticamente al cargar la pagina.

Salida: append a precios_automotor.csv en el mismo repo.
"""

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
log = logging.getLogger("facilito-automotor")

FACILITO_URL = (
    "https://www.facilito.gob.pe/facilito/pages/facilito/buscadorAGranelGLP.jsp"
)

# Codigos geograficos (mismos que el scraper de envasado)
COD_DEPARTAMENTO = "150000"  # LIMA
COD_PROVINCIA    = "150100"  # LIMA
COD_DISTRITO     = "150119"  # LURIN

# Archivos de salida / diagnostico
CSV_PATH        = Path("precios_automotor.csv")
DEBUG_PNG       = "error_debug_automotor.png"
DEBUG_HTML      = "page_debug_automotor.html"

CSV_HEADERS = [
    "fecha_extraccion",
    "hora_extraccion",
    "distrito",
    "establecimiento",
    "direccion",
    "telefono",
    "precio",
    "unidad_medida",
    "producto",
    "fuente",
]


def _guardar_diagnostico(page):
    """Guarda captura y HTML para inspeccionar que mostro la pagina."""
    try:
        page.screenshot(path=DEBUG_PNG, full_page=True)
        Path(DEBUG_HTML).write_text(page.content(), encoding="utf-8")
        log.info("Diagnostico guardado (captura + HTML)")
    except Exception as e:
        log.error(f"No se pudo guardar diagnostico: {e}")


# -----------------------------------------------------------------------------
# 1. Scraping
# -----------------------------------------------------------------------------
def scrape_lurin_automotor() -> list[dict]:
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

            # Seleccionar producto "GLP - Granel" por su TEXTO (mas robusto que el value)
            log.info("Seleccionando producto GLP - Granel...")
            estado = page.evaluate("""
                () => {
                    const sel = document.querySelector('select[name="producto"]');
                    if (!sel) return 'sin-select-producto';
                    let encontrado = false;
                    for (const opt of sel.options) {
                        if ((opt.text || '').toUpperCase().includes('GRANEL')) {
                            sel.value = opt.value;
                            encontrado = true;
                            break;
                        }
                    }
                    if (typeof cambiarProducto === 'function') {
                        cambiarProducto();
                        return encontrado ? 'ok' : 'granel-no-encontrado';
                    }
                    return 'sin-funcion-cambiarProducto';
                }
            """)
            log.info(f"Estado seleccion producto: {estado}")
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(2500)

            # Leer la tabla de resultados
            filas = page.evaluate("""
                () => {
                    const out = [];
                    const rows = document.querySelectorAll('table tbody tr');
                    for (const r of rows) {
                        const th = r.querySelector('th');
                        const cells = r.querySelectorAll('td');
                        if (th && cells.length >= 5) {
                            out.push({
                                distrito:        th.innerText.trim(),
                                establecimiento: cells[0].innerText.trim(),
                                direccion:       cells[1].innerText.trim(),
                                telefono:        cells[2].innerText.trim(),
                                precio:          cells[3].innerText.trim(),
                                unidad_medida:   cells[4].innerText.trim()
                            });
                        }
                    }
                    return out;
                }
            """)

            for f in filas:
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
                    "establecimiento":  f["establecimiento"],
                    "direccion":        f["direccion"],
                    "telefono":         f["telefono"],
                    "precio":           precio_num,
                    "unidad_medida":    f["unidad_medida"],
                    "producto":         "GLP - Granel",
                    "fuente":           "Facilito Osinergmin",
                })

            log.info(f"Total filas extraidas: {len(todas_filas)}")
            if not todas_filas:
                log.warning("0 filas: guardando captura y HTML para diagnostico")
                _guardar_diagnostico(page)

            return todas_filas

        except Exception as e:
            log.error(f"Error durante scraping: {e}")
            _guardar_diagnostico(page)
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

    if not CSV_PATH.exists():
        log.info(f"Creando archivo nuevo: {CSV_PATH}")
        with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()

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
        filas = scrape_lurin_automotor()
        if not filas:
            log.error("Cero filas extraidas - abortando sin escribir")
            sys.exit(1)

        append_to_csv(filas)
        log.info(f"OK - {len(filas)} gasocentros extraidos en LURIN")

    except Exception as e:
        log.error(f"Ejecucion fallo: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
