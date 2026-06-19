"""
Extractor diario de precios GLP envasado de Facilito (Osinergmin).
Alcance: TODOS los distritos de la provincia de LIMA, para balones de 15 Kg y 45 Kg.

Estrategia robusta: recarga la pagina desde cero para CADA distrito, evitando
que el estado acumulado de la pagina rompa el formulario a mitad del recorrido.

Salida: append a precios.csv en el mismo repo.
"""

import sys
import csv
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from playwright.sync_api import sync_playwright

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

COD_DEPARTAMENTO = "150000"  # LIMA
COD_PROVINCIA    = "150100"  # LIMA (provincia)

PRODUCTOS = [
    {"codigo": "53", "nombre": "15 Kg"},
    {"codigo": "54", "nombre": "45 Kg"},
]

CSV_PATH   = Path("precios.csv")
DEBUG_PNG  = "error_debug.png"
DEBUG_HTML = "page_debug.html"

CSV_HEADERS = [
    "fecha_extraccion", "hora_extraccion", "distrito", "marca",
    "establecimiento", "direccion", "telefono", "precio", "producto", "fuente",
]


def _guardar_diagnostico(page):
    try:
        page.screenshot(path=DEBUG_PNG, full_page=True)
        Path(DEBUG_HTML).write_text(page.content(), encoding="utf-8")
        log.info("Diagnostico guardado (captura + HTML)")
    except Exception as e:
        log.error(f"No se pudo guardar diagnostico: {e}")


def _seleccionar_lima(page):
    """Desde una pagina recien cargada, selecciona Departamento y Provincia LIMA."""
    page.goto(FACILITO_URL, wait_until="networkidle", timeout=60000)
    page.evaluate(f"makeAction({COD_DEPARTAMENTO})")
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_timeout(2500)
    page.evaluate(f"""
        document.querySelector('select[name="provincia"]').value = '{COD_PROVINCIA}';
        cambiarProvincia();
    """)
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_timeout(1500)


def _leer_distritos(page) -> list[dict]:
    return page.evaluate("""
        () => {
            const sel = document.querySelector('select[name="distrito"]');
            if (!sel) return [];
            const out = [];
            for (const opt of sel.options) {
                const v = (opt.value || '').trim();
                const t = (opt.text || '').trim();
                if (/^\\d{6}$/.test(v) && v !== '150000' && v !== '150100') {
                    out.push({codigo: v, nombre: t});
                }
            }
            return out;
        }
    """)


def _leer_tabla(page) -> list[dict]:
    return page.evaluate("""
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


def scrape_lima_envasado() -> list[dict]:
    todas_filas: list[dict] = []
    now_lima = datetime.now(ZoneInfo("America/Lima"))
    fecha_str = now_lima.strftime("%Y-%m-%d")
    hora_str  = now_lima.strftime("%H:%M:%S")

    log.info("Iniciando navegador Playwright (headless)...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="es-PE",
        )
        page = context.new_page()

        try:
            # Paso 1: obtener la lista de distritos
            log.info("Obteniendo lista de distritos de LIMA...")
            _seleccionar_lima(page)
            distritos = _leer_distritos(page)
            log.info(f"Distritos encontrados: {len(distritos)}")
            if not distritos:
                log.warning("No se pudo leer la lista de distritos")
                _guardar_diagnostico(page)
                return []

            # Paso 2: recorrer distritos, recargando la pagina para cada uno
            for dist in distritos:
                log.info(f"--- Distrito {dist['nombre']} ({dist['codigo']}) ---")
                try:
                    _seleccionar_lima(page)  # pagina fresca + LIMA/LIMA
                    page.evaluate(f"""
                        document.querySelector('select[name="distrito"]').value = '{dist['codigo']}';
                        cambiarDistrito();
                    """)
                    page.wait_for_load_state("networkidle", timeout=60000)
                    page.wait_for_timeout(1500)

                    for prod in PRODUCTOS:
                        page.evaluate(f"""
                            document.querySelector('select[name="producto"]').value = '{prod['codigo']}';
                            cambiarProducto();
                        """)
                        page.wait_for_load_state("networkidle", timeout=60000)
                        page.wait_for_timeout(1500)

                        filas_producto = _leer_tabla(page)
                        if not filas_producto:
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

                        log.info(f"  {dist['nombre']} / {prod['nombre']}: {len(filas_producto)} establecimientos")

                except Exception as e:
                    log.warning(f"Distrito {dist['nombre']} fallo, se omite: {e}")
                    continue

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


def append_to_csv(filas: list[dict]):
    if not filas:
        log.warning("Sin filas para agregar - skip CSV")
        return
    if not CSV_PATH.exists():
        log.info(f"Creando archivo nuevo: {CSV_PATH}")
        with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        for row in filas:
            writer.writerow(row)
    log.info(f"Agregadas {len(filas)} filas a {CSV_PATH}")


def main():
    try:
        filas = scrape_lima_envasado()
        if not filas:
            log.error("Cero filas extraidas - abortando sin escribir")
            sys.exit(1)
        append_to_csv(filas)
        distritos_con_data = len({f["distrito"] for f in filas})
        log.info(f"OK - {len(filas)} filas en {distritos_con_data} distritos")
    except Exception as e:
        log.error(f"Ejecucion fallo: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
