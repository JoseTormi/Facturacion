# Extraccion de facturas

Proyecto base para automatizar este flujo:

1. Entrar a diferentes plataformas o portales.
2. Descargar facturas en PDF.
3. Extraer datos clave de cada factura.
4. Consolidar la informacion en un archivo Excel.

## Requisitos

- Python 3.10 o superior.
- Navegadores de Playwright para automatizar portales web.
- Opcional: Tesseract OCR si algunas facturas son imagen escaneada.

Si en Windows `python` abre la tienda de Microsoft o no ejecuta, instala Python desde `python.org` y marca la opcion **Add python.exe to PATH**.

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
playwright install chromium
```

Copia el archivo de ejemplo de variables:

```powershell
Copy-Item .env.example .env
```

Edita `.env` con tus credenciales reales.

## Uso rapido

Extraer facturas que ya esten descargadas en `data/downloads`:

```powershell
facturas extract-local
```

Ejecutar una plataforma configurada:

```powershell
facturas run-platform example
```

El Excel se genera en `data/output/facturas.xlsx`.

## API local

Tambien puedes levantar la API HTTP:

```powershell
uvicorn invoice_automation.api:app --host 0.0.0.0 --port 8000
```

Rutas principales:

- `GET /health`: estado del servicio.
- `GET /platforms`: plataformas registradas.
- `POST /extract`: recibe PDFs y devuelve JSON con los datos extraidos.
- `POST /extract/excel`: recibe PDFs y devuelve `facturas.xlsx`.

La documentacion interactiva queda en `http://localhost:8000/docs`.

## Despliegue en Render

El repo incluye `Dockerfile` y `render.yaml`. En Render, crea un **Blueprint**
desde este repositorio:

```text
https://github.com/JoseTormi/Facturacion.git
```

Render construira la imagen Docker y publicara la API usando `/health` como
health check.

## Flujo del sistema

El diagrama tecnico del recorrido de datos esta en [`docs/flujo_sistema.md`](docs/flujo_sistema.md).

## OCR opcional

Para facturas escaneadas, instala las dependencias extra:

```powershell
pip install -e ".[ocr]"
```

Tambien debes instalar Tesseract OCR en Windows y dejarlo disponible en el PATH.

## Estructura

```text
src/invoice_automation/
  connectors/        Automatizaciones por plataforma
  extractor.py       Lectura de PDFs y reglas de extraccion
  exporter.py        Generacion del Excel
  models.py          Modelo comun de factura
  main.py            Comandos de consola
```

## Como agregar una plataforma real

1. Crea un archivo en `src/invoice_automation/connectors/`, por ejemplo `proveedor_x.py`.
2. Hereda de `BaseConnector`.
3. Implementa `download_invoices`.
4. Registra el conector en `src/invoice_automation/connectors/registry.py`.

Cada portal tiene pantallas, botones y filtros distintos. Por eso el proyecto usa conectores: la parte especifica de cada plataforma queda aislada.

## Datos extraidos

El extractor intenta identificar:

- Numero de factura.
- Fecha de emision.
- Nit/emisor.
- Cliente/receptor.
- Subtotal.
- IVA/impuestos.
- Total.
- Moneda.
- Ruta del PDF original.

Las reglas estan en `extractor.py` y se pueden ajustar segun el formato de tus facturas.
