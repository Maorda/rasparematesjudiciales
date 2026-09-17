import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Incorporar la raíz al path de Python para resolver las importaciones de los módulos locales
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Importación de los componentes de la Línea Base Rígida de tu arquitectura
from src.core.storage.history_manager import RemajuHistoryManager
from src.auth.login_handler import RemajuAuthenticator
from src.scraper.search import RemajuSearchScraper
from src.scraper.extractor import RemajuExtractorScraper

# Carga de la clase del servicio OCR local y offline de ddddocr
from src.scraper.ocr_service import CaptchaResolver

# Carga de los componentes nativos institucionales de Google Drive del script estable de Colab
import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Configuración de Google Drive heredada al 100% de tu script estable de Colab
CARPETA_RAIZ_ID = "1lsNX5GEiM7-Ho2kTbu00AqfckAnyWyFl"
SCOPES = ['https://www.googleapis.com/auth/drive','https://www.googleapis.com/auth/drive.readonly']

def subir_pdf_a_google_drive(ruta_archivo_local, nombre_archivo):
    """Función de persistencia atómica nativa original del script estable de Colab."""
    try:
        load_dotenv()
        PRIVATE_KEY_RAW = os.getenv("GOOGLE_PRIVATE_KEY", "")
        FORMATTED_PRIVATE_KEY = PRIVATE_KEY_RAW.replace('\\n', '\n')
        CREDENTIALS_DICT = {
            "type": "service_account",
            "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
            "private_key": FORMATTED_PRIVATE_KEY,
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('GOOGLE_CLIENT_EMAIL')}"
        }
        creds = service_account.Credentials.from_service_account_info(CREDENTIALS_DICT, scopes=SCOPES)
        service = build('drive', 'v3', credentials=creds)

        nombre_carpeta_dia = datetime.datetime.now().strftime('%Y-%m-%d')

        query = f"mimeType='application/vnd.google-apps.folder' and name='{nombre_carpeta_dia}' and '{CARPETA_RAIZ_ID}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get('files', [])

        if folders:
            id_carpeta_dia = folders[0]['id']
        else:
            folder_metadata = {
                'name': nombre_carpeta_dia,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [CARPETA_RAIZ_ID]
            }
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            id_carpeta_dia = folder.get('id')
            print(f"  -> [DRIVE] Carpeta creada para la fecha: {nombre_carpeta_dia}")

        file_metadata = {
            'name': nombre_archivo,
            'parents': [id_carpeta_dia]
        }
        media = MediaFileUpload(ruta_archivo_local, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()

        print(f"  -> [OK] PDF subido exitosamente a Google Drive (ID: {file.get('id')})")
        return file.get('id')
    except Exception as e:
        print(f"  -> [WARNING] No se pudo subir el archivo a Google Drive: {e}")
        return None

# Configuración global del sistema de bitácoras (Logging)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

# Carga del archivo de configuración global config.json
CONFIG_PATH = Path(os.path.dirname(os.path.abspath(__file__))) / "config.json"
try:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        APP_CONFIG = json.load(f)
    logger.info("[INFO] Configuración 'config.json' cargada exitosamente.")
except Exception as e:
    logger.error(f"[ERROR] No se pudo cargar 'config.json': {e}")
    APP_CONFIG = {}

async def main():
    logger.info("Iniciando bot orquestador asíncrono lineal con PLAYWRIGHT para REMAJU...")
    load_dotenv()
    
    # 1. Instanciar RemajuHistoryManager apuntando al archivo local de persistencia atómica
    history_manager = RemajuHistoryManager("historial_procesados.json")
    
    # 2. Inicializar el resolvedor de captcha local de ddddocr
    captcha_builder = CaptchaResolver()
    
    # Definición de variables de entorno y parámetros de negocio
    url_api_backend = "https://backendremaju.koyeb.app/registrar-remate-judicial"
    tipo_inmueble_filtro = "1"  # Mantenido por firma de compatibilidad
    ruta_local_descargas = './descargas_resoluciones'
    
    # 3. Lanzar el contexto asíncrono nativo de Playwright
    async with async_playwright() as p:
        logger.info("Lanzando instancia automatizada de Chromium con Playwright...")
        browser = await p.chromium.launch(headless=False)  # Cambiar a True para ejecutarlo en segundo plano
        
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            accept_downloads=True
        )
        page = await context.new_page()
        
        try:
            # 4. Instanciar RemajuAuthenticator y ejecutar el inicio de sesión robótico por hardware
            authenticator = RemajuAuthenticator(page, captcha_builder, creds_path="autenticacion.json")
            creds = authenticator.load_credentials()
            url_login_absoluta = f"{creds['url_base']}{creds['url_login_path']}"
            
            # Ejecutar el Login (Maneja la carrera asíncrona contra el div.ui-growl-item y .press('Tab'))
            login_success = await authenticator.execute_login()
            if not login_success:
                logger.error("[ERROR] Se agotaron los intentos de Login. Abortando ejecución.")
                await browser.close()
                return
                
            logger.info("[OK] Autenticación completada exitosamente. Bot situado en inicio.xhtml")
            
            # 5. Instanciar RemajuSearchScraper para aplicar filtros de PrimeFaces y menús acordeón
            search_scraper = RemajuSearchScraper(page, history_manager=history_manager)
            await search_scraper.navigate_to_search_module()
            await search_scraper.apply_search_filters(tipo_inmueble_filtro)
            
            # 6. Instanciar RemajuExtractorScraper inyectando el Page de Playwright y el config.json
            extractor = RemajuExtractorScraper(page, config_path="config.json")
            
            pagina_num = 1
            remates_finales_json = []
            
            # 7. Bucle Principal de la Rutina Diaria del Paginador de REMAJU
            while True:
                logger.info(f"\n[INFO] Extrayendo datos de la página del paginador #{pagina_num}...")
                await extractor.esperar_sincronizacion_primefaces()
                await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                
                # Evaluar las tarjetas presentes en la grilla exterior para aislar sus títulos
                remates_pagina = await page.evaluate('''
                    () => {
                        const resultados = [];
                        document.querySelectorAll('div.card.azul').forEach(card => {
                            const header = card.querySelector('.label-danger, .h6')?.innerText.trim() || '';
                            if (header) {
                                resultados.push({
                                    titulo_tarjeta: header,
                                    archivo_resolucion: null
                                });
                            }
                        });
                        return resultados;
                    }
                ''')
                
                num_tarjetas = len(remates_pagina)
                logger.info(f"[INFO] Se encontraron {num_tarjetas} registros en la grilla de la página actual.")
                
                # 8. Iteración secuencial sobre las filas de la tabla de resultados de PrimeFaces
                for i in range(num_tarjetas):
                    await extractor.esperar_sincronizacion_primefaces()
                    await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                    
                    tarjeta_actual = page.locator("div.card.azul").nth(i)
                    btn_detalle = tarjeta_actual.locator("button:has-text('Detalle')").first
                    
                    if await btn_detalle.count() > 0:
                        # Extraer los datos de la tarjeta exterior para evaluar duplicados históricos antes del click
                        raw_title = await tarjeta_actual.locator(".label-danger, .h6").first.inner_text()
                        if "REMATE N°" in raw_title and " - " in raw_title:
                            parts = raw_title.split(" - ")
                            numero_expediente = parts[0].strip()
                            numero_convocatoria = parts[1].strip()
                        else:
                            numero_expediente = f"EXP-FALLBACK-{i+1}"
                            numero_convocatoria = "PRIMERA CONVOCATORIA"
                            
                        # Control de Duplicados Perimetral Histórico
                        if history_manager.is_processed(numero_expediente, numero_convocatoria):
                            logger.info(f"  -> [HISTORIAL] El expediente {numero_expediente} ({numero_convocatoria}) ya consta como procesado. Saltando.")
                            continue
                            
                        logger.info(f"\n[INFO] Procesando registro {i+1} de {num_tarjetas} -> Expediente: {numero_expediente}")
                        
                        # === PASO A: ENTRAR AL DETALLE INTERNO ===
                        try:
                            await btn_detalle.click(force=True)
                            await page.wait_for_selector("button:has-text('Regresar'), a:has-text('Regresar')", state="visible", timeout=15000)
                            await extractor.esperar_sincronizacion_primefaces()
                        except Exception as e:
                            logger.error(f"  -> [ERROR] Falló la transición hacia la ficha de detalle: {e}")
                            continue
                            
                        btn_regresar = page.locator("button:has-text('Regresar'), a:has-text('Regresar')").first
                        
                        # === PASO B: VERIFICACIÓN CRÍTICA DE MATERIA (CORTOCIRCUITO DE ALIMENTOS) ===
                        xpath_materia = "//div[contains(@class, 'ui-g')][div[contains(text(), 'Materia')]]/div[contains(@class, 'text-justify') or contains(@class, 'ui-panelgrid-cell')][last()]"
                        try:
                            materia_text = (await page.locator(xpath_materia).first.inner_text(timeout=3000)).strip()
                        except:
                            materia_text = ""
                            
                        if materia_text == "Pago por alimentos":
                            logger.info("  -> [CORTOCIRCUITO] Materia 'Pago por alimentos' detectada. Abortando extracción de pestañas.")
                            try:
                                await btn_regresar.click(force=True)
                                await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                                await extractor.esperar_sincronizacion_primefaces()
                            except Exception as ex:
                                logger.error(f"  -> [ERROR] Problema al ejecutar retroceso por cortocircuito: {ex}")
                            continue
                        
                        # === PASO C: EXTRAER DATOS INTEGRALES POR ESCENARIOS TABS ===
                        try:
                            detalle_extraido = await extractor.extract_tab_remate_completo()
                            remates_pagina[i].update(detalle_extraido)
                        except Exception as e:
                            logger.error(f"  -> [ERROR] Falló la extracción de los escenarios por pestañas: {e}")
                            detalle_extraido = {"remate": {"expediente": numero_expediente}}
                            
                        # === PASO D: DESCARGA DE PDF POR STREAM DE RED ===
                        nombre_pdf_descargado = await extractor.download_resolucion_pdf(numero_expediente, ruta_local_descargas)
                        
                        # === PASO E: ADAPTACIÓN DE DTO DINÁMICO Y PERSISTENCIA HÍBRIDA ===
                        dto_mapeado_final = extractor.adaptar_a_dto(remates_pagina[i], nombre_pdf_descargado)
                        remates_finales_json.append(dto_mapeado_final)
                        
                        # Invocación directa a la función nativa global estable de Google Drive
                        if nombre_pdf_descargado:
                            ruta_local_pdf_completa = os.path.join(ruta_local_descargas, nombre_pdf_descargado)
                            if os.path.exists(ruta_local_pdf_completa):
                                logger.info("  -> [DRIVE] Subiendo archivo PDF de resolución a Google Drive...")
                                subir_pdf_a_google_drive(ruta_local_pdf_completa, nombre_pdf_descargado)
                                
                        # Registrar en el historial de persistencia atómica
                        history_manager.save_processed(numero_expediente, numero_convocatoria)
                        
                        # Imprimir diagnóstico JSON en consola
                        print("\n[DIAGNÓSTICO JSON] Registro DTO único adaptado para transmisión:")
                        print(json.dumps(dto_mapeado_final, indent=4, ensure_ascii=False))
                        
                        # Enviar el DTO a la API del backend
                        logger.info("[API] Transmitiendo registro hacia el ODM del Backend...")
                        try:
                            import aiohttp
                            async with aiohttp.ClientSession() as session:
                                headers_api = {'Content-Type': 'application/json'}
                                async with session.post(url_api_backend, json=dto_mapeado_final, headers=headers_api) as response:
                                    if response.status in (200, 201):
                                        logger.info(f"  -> [OK] Registro insertado en base de datos correctamente (Status: {response.status})")
                                    else:
                                        err_resp = await response.text()
                                        logger.warning(f"  -> [WARNING] Error devuelto por la API. Status: {response.status} - Detalle: {err_resp}")
                        except Exception as api_err:
                            logger.error(f"  -> [ERROR] Falló la conexión de red al transmitir el DTO: {api_err}")
                            
                        # === PASO F: CERRAR CICLO DE LA FICHA (RETORNO SEGURO) ===
                        try:
                            logger.info("    -> Cerrando ciclo de ficha. Regresando a la bandeja general...")
                            await btn_regresar.click(force=True)
                            await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                        except Exception as e:
                            logger.error(f"  -> [ERROR] Problema al regresar a la lista de resultados: {e}")
                            
                        await extractor.esperar_sincronizacion_primefaces()
                        await asyncio.sleep(1.0)
                        
                # 9. Gestión y orquestación del paginador global (.ui-paginator-next)
                btn_siguiente = page.locator("a.ui-paginator-next:not(.ui-state-disabled)").first
                if await btn_siguiente.is_visible():
                    pagina_num += 1
                    await btn_siguiente.click(force=True)
                    await extractor.esperar_sincronizacion_primefaces()
                else:
                    logger.info("\n[OK] Fin de registros alcanzado. El paginador no reporta más páginas. Extracción finalizada.")
                    break
                    
            # Consolidar todos los datos procesados en un archivo de respaldo local JSON
            if remates_finales_json:
                archivo_salida = 'remates_extraidos.json'
                with open(archivo_salida, 'w', encoding='utf-8') as f:
                    json.dump(remates_finales_json, f, indent=4, ensure_ascii=False)
                logger.info(f"\n[ÉXITO] Todos los datos consolidados han sido guardados en: {archivo_salida}")
                
            await browser.close()
            logger.info("Orquestación completada exitosamente con Playwright. Suite en verde.")
            
        except Exception as e:
            logger.error(f"[ERROR] Falló la orquestación asíncrona general en main.py: {str(e)}")
            try:
                await browser.close()
            except Exception:
                pass

if __name__ == "__main__":
    asyncio.run(main())