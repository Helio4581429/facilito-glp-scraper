# Extracción Diaria Precios GLP — Facilito Osinergmin

Extrae diariamente los precios de **TODOS los establecimientos en LURIN**
para **balones de 15 Kg y 45 Kg** desde
[Facilito de Osinergmin](https://www.facilito.gob.pe/facilito/) y los
guarda en un Excel histórico en SharePoint. Power BI Service consume ese
Excel y refresca automáticamente.

```
GitHub Actions (cron diario 07:00 Lima)
        │
        ▼
   Python + Playwright (Chromium headless)
        │
        ▼
  Facilito  →  reCAPTCHA v3 (resuelto por browser real)
        │
        ▼
  Loop sobre [15 Kg, 45 Kg]  →  extrae N establecimientos × 2 productos
        │
        ▼
  Microsoft Graph API  →  SharePoint Excel (append N filas)
        │
        ▼
  Power BI Service  →  refresh diario automático
```

**Salida esperada por día:** ~2N filas (N = nº de plantas envasadoras
activas en LURIN reportando a Facilito ese día × 2 productos).
Típicamente entre 2 y 10 filas/día.

---

## 📁 Estructura del proyecto

```
facilito-glp/
├── scrape_facilito.py       Script principal (Playwright + Graph)
├── requirements.txt          Dependencias Python
├── historico_glp.xlsx        Template Excel (subir 1 vez a SharePoint)
├── .github/workflows/
│   └── daily.yml             Workflow GitHub Actions con cron diario
└── README.md                 Esta guía
```

---

## ⚙️ Setup inicial (una sola vez, ~30 min)

### 1. Subir el Excel template a SharePoint

1. Descarga `historico_glp.xlsx` de este proyecto.
2. Súbelo a SharePoint donde quieras almacenarlo, por ejemplo:
   `Documentos compartidos/PreciosGLP/historico_glp.xlsx`
3. **Importante:** verifica que la hoja se llame exactamente `Precios GLP`
   (el script la busca por nombre).
4. Anota la ruta completa — la usarás en el paso 4.

### 2. Crear App Registration en Azure AD

GitHub Actions necesita credenciales para escribir en SharePoint.

1. Ve a [portal.azure.com](https://portal.azure.com) → **Entra ID** /
   **Azure Active Directory** → **App registrations** → **New registration**
2. Nombre: `Facilito-GLP-Scraper`
3. Supported account types: **Single tenant**
4. Click **Register**
5. En el **Overview**, anota:
   - **Application (client) ID** → será `AZURE_CLIENT_ID`
   - **Directory (tenant) ID** → será `AZURE_TENANT_ID`
6. Menú izquierdo → **Certificates & secrets** → **New client secret**:
   - Descripción: `github-actions`
   - Expira: **24 meses** (anótalo para renovar antes)
   - Click Add → **copia el `Value` inmediatamente** (no se vuelve a mostrar)
   - Este es `AZURE_CLIENT_SECRET`
7. Menú izquierdo → **API permissions** → **Add a permission**:
   - **Microsoft Graph** → **Application permissions**
   - Agregar: `Sites.Selected` *(da acceso solo a sites que autorices
     explícitamente — más seguro que `Sites.ReadWrite.All`)*
   - Click **Grant admin consent for [tu tenant]** *(necesitas ser Global
     Admin o pedírselo a TI)*

### 3. Autorizar el site específico (Sites.Selected)

`Sites.Selected` no da acceso a nada por defecto — hay que autorizar el
site puntual donde está el Excel. Esto se hace una sola vez. Pídeselo a
TI o, si tienes permisos de Global Admin, ejecuta en PowerShell:

```powershell
# Requiere módulo Microsoft.Graph PowerShell
Install-Module Microsoft.Graph -Scope CurrentUser

Connect-MgGraph -Scopes "Sites.FullControl.All"

# Reemplaza con el nombre real de tu site
$siteId = (Get-MgSite -Search "Finanzas").Id

# Reemplaza con el Client ID del paso 2.5
$appId = "TU_AZURE_CLIENT_ID_AQUI"

$params = @{
    roles = @("write")
    grantedToIdentities = @(
        @{ application = @{ id = $appId; displayName = "Facilito-GLP-Scraper" } }
    )
}
New-MgSitePermission -SiteId $siteId -BodyParameter $params
```

### 4. Configurar GitHub Secrets

1. Sube este proyecto a un repositorio **privado** en GitHub.
2. Ve al repo → **Settings** → **Secrets and variables** → **Actions** →
   **New repository secret**
3. Crea estos 6 secrets:

| Secret name | Ejemplo |
|---|---|
| `AZURE_TENANT_ID` | `c3f5d4a1-abcd-...` |
| `AZURE_CLIENT_ID` | `a7d2b3c4-1234-...` |
| `AZURE_CLIENT_SECRET` | el `Value` copiado en paso 2.6 |
| `SP_SITE_HOST` | `molinosasociados.sharepoint.com` |
| `SP_SITE_PATH` | `/sites/Finanzas` (o el nombre real de tu site) |
| `SP_FILE_PATH` | `/Documentos compartidos/PreciosGLP/historico_glp.xlsx` |

> **Nota sobre `SP_FILE_PATH`:** empieza con `/` y usa el nombre exacto
> de la biblioteca como aparece en la URL del Excel cuando lo abres en
> el navegador. Si tu SharePoint está en inglés será `/Shared Documents/...`,
> en español `/Documentos compartidos/...` o `/Documents/...` según versión.

### 5. Primera ejecución manual

1. Repo → tab **Actions** → workflow **"Extraer Precios GLP Facilito (Diario)"**
2. Click **Run workflow** → **Run workflow**
3. En 2-3 min debe aparecer ✅
4. Si falla, revisa los logs y descarga el artifact `error-screenshot`
5. Abre tu Excel en SharePoint y verifica que se agregaron las filas

### 6. Conectar Power BI

1. **Power BI Desktop** → **Obtener datos** → **SharePoint Folder**
2. URL del site: `https://molinosasociados.sharepoint.com/sites/Finanzas`
3. **Combinar archivos** → filtra por nombre = `historico_glp.xlsx` →
   selecciona la hoja `Precios GLP`
4. Modela y guarda
5. **Publish** a Power BI Service
6. Power BI Service → tu **Dataset** → **Settings** → **Scheduled
   refresh** → activa refresh diario a las **08:00 Lima** (1 h después
   del scraping para tener buffer si el job se atrasa)

---

## 📊 Estructura del Excel histórico

| # | Columna | Tipo | Ejemplo |
|---|---|---|---|
| 1 | Fecha Extracción | Date | 2026-05-27 |
| 2 | Hora Extracción | Time | 07:02:14 |
| 3 | Distrito | Text | LURIN |
| 4 | Marca | Text | Costa Gas / Ω MEGA / etc |
| 5 | Establecimiento | Text | COSTAGAS |
| 6 | Dirección | Text | MZ. E LOTE 13-A, CALLE 6, LAS PRADERAS DE LURIN |
| 7 | Teléfono | Text | 016269999/941450935 |
| 8 | Precio Venta (S/) | Number | 224.75 |
| 9 | Producto | Text | 15 Kg / 45 Kg |
| 10 | Fuente | Text | Facilito Osinergmin |

> Cada combinación **fecha + establecimiento + producto** es única.
> Power BI puede usar [Fecha + Establecimiento + Producto] como key.

---

## 🔧 Cómo modificar parámetros

| Cambio | Dónde editar |
|---|---|
| Otro distrito | `scrape_facilito.py` → `COD_DISTRITO` |
| Agregar 10 Kg, 5 Kg, 3 Kg | `scrape_facilito.py` → lista `PRODUCTOS` |
| Otra hora cron | `.github/workflows/daily.yml` → línea `cron:` (UTC) |
| Otros distritos en lote | Modificar `main()` para iterar lista de distritos |

**Códigos de productos** (Facilito):

| Producto | Código |
|---|---|
| 3 Kg  | 50 |
| 5 Kg  | 51 |
| 10 Kg | 52 |
| 15 Kg | **53** ✓ |
| 45 Kg | **54** ✓ |

**Códigos de ubicación** (capturados del DOM):

| Item | Código |
|---|---|
| Departamento LIMA | 150000 |
| Provincia LIMA | 150100 |
| Distrito LURIN | 150119 |

---

## 💡 Sugerencias de análisis en Power BI

Con esta data histórica puedes construir:

1. **Tendencia de precio diaria** — línea Costa Gas 45 Kg vs tiempo
2. **Posicionamiento competitivo** — Costa Gas vs promedio Lurín por producto
3. **Spread 15 Kg vs 45 Kg** — para detectar oportunidades de arbitraje
4. **Volatilidad** — desviación estándar 30 días móvil
5. **Alertas DAX** — si Costa Gas sube/baja >X% vs promedio competencia

**Medidas DAX útiles** *(añadir en el modelo PBI):*

```dax
Precio Promedio Distrito =
    CALCULATE(
        AVERAGE('Precios GLP'[Precio Venta (S/)]),
        ALLEXCEPT('Precios GLP', 'Precios GLP'[Fecha Extracción], 'Precios GLP'[Producto])
    )

Spread Costa Gas vs Mercado =
    VAR PrecioCG =
        CALCULATE(
            AVERAGE('Precios GLP'[Precio Venta (S/)]),
            'Precios GLP'[Marca] = "Costa Gas"
        )
    VAR PromedioOtros =
        CALCULATE(
            AVERAGE('Precios GLP'[Precio Venta (S/)]),
            'Precios GLP'[Marca] <> "Costa Gas"
        )
    RETURN PrecioCG - PromedioOtros
```

---

## 🛟 Troubleshooting

**El workflow corre pero Excel no se actualiza:**
- ¿Diste permiso `Sites.Selected` específicamente al site? (paso 3)
- Logs del Action: error 403 = permisos; 404 = ruta mal escrita;
  401 = credenciales mal copiadas

**Playwright timeout:**
- Facilito a veces tarda. Sube `timeout=60000` a `90000` en el código
- Cambia el cron a horario menos saturado (ej. 06:00 Lima)

**Extrae 0 filas un día puntual:**
- Puede ser que Osinergmin esté en mantenimiento, o no haya plantas
  reportando ese día. El script aborta sin escribir nada al Excel
  para mantener integridad
- Revisa el screenshot del artifact

**Quieres deduplicar (evitar 2 filas mismo día/establecimiento/producto):**
- El script siempre hace append. Para deduplicar, agrega validación en
  `append_to_sharepoint_excel()` que lea filas existentes y omita
  duplicados de la fecha actual

**reCAPTCHA empieza a bloquear (escenario futuro):**
- Si Osinergmin sube a reCAPTCHA v2 con desafío visual, el flujo se
  rompe. Solución: integrar 2Captcha (~$2 USD/1000 captchas, ~$0.06/mes)

---

## 💰 Costo total

| Componente | Costo mensual |
|---|---|
| GitHub Actions (repo privado, ~3 min/día × 30) | **$0** (cuota gratis 2000 min/mes) |
| Azure AD App Registration | **$0** |
| SharePoint storage (~50 KB/año) | **$0** (M365 existente) |
| Power BI refresh | **$0** (licencia Pro existente) |
| **TOTAL** | **$0 / mes** |

---

## 🔐 Notas de seguridad

- El `AZURE_CLIENT_SECRET` da acceso programático — trátalo como contraseña
- Renovar el client secret cada 24 meses (recordatorio recomendado en calendario)
- `Sites.Selected` limita el daño potencial al único site autorizado
- El repo de GitHub debe ser **privado** (los secrets no se exponen,
  pero el código sí muestra la estructura interna que es info sensible
  de tu empresa)
