# src/scraper/extractor.py
import asyncio
import json
import io
import logging
import os
import tempfile
from pathlib import Path

# Importación para manejar el protocolo CDP en nodriver (necesario para descargas reales)
import nodriver.cdp.browser as browser_cdp

# Configuración básica de logging para auditoría de pestañas internas
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RemajuExtractorError(Exception):
    """Excepciones de extracción de la ficha detallada."""
    pass

class RemajuExtractorScraper:
    def __init__(self, page, creds_path: str = "autenticacion.json"):
        """
        Inicializa el extractor de la ficha detallada por pestañas de REMAJU.
        :param page: Objeto de página de nodriver.
        :param creds_path: Ruta al archivo JSON de configuración.
        """
        self.page = page
        self.creds_path = Path(creds_path)
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Carga y valida la configuración fragmentada (url_base, paths)."""
        if not self.creds_path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {self.creds_path}")
        
        with open(self.creds_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            req = ["url_base", "url_search_path", "url_detail_path"]
            if not all(k in data for k in req):
                raise ValueError(f"Faltan llaves de entorno en el JSON: {req}")
            return data

    async def _wait_for_spinner_to_disappear(self):
        """Espera activa para la desaparición del overlay de carga 'dlgEstado'."""
        for _ in range(40):
            is_visible = await self.page.evaluate("""
                () => {
                    const el = document.getElementById('dlgEstado');
                    return el ? window.getComputedStyle(el).display !== 'none' : false;
                }
            """)
            if not is_visible:
                await asyncio.sleep(0.5)
                return
            await asyncio.sleep(0.5)
        logger.warning("Timeout del spinner. El flujo puede volverse inestable.")

    async def _get_text_by_xpath(self, xpath: str) -> str:
        """Helper para extraer texto robusto usando XPath en nodriver vía JS."""
        script = f"""
            (() => {{
                const el = document.evaluate("{xpath}", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                return el ? el.textContent.trim() : "";
            }})()
        """
        return await self.page.evaluate(script)

    async def _click_by_xpath(self, xpath: str) -> bool:
        """Helper para ejecutar un click directo sobre un elemento XPath vía JS."""
        script = f"""
            (() => {{
                const el = document.evaluate("{xpath}", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if(el) {{ el.click(); return true; }}
                return false;
            }})()
        """
        return await self.page.evaluate(script)

    async def extract_tab_remate(self) -> dict:
        """Extrae de manera integral todos los datos del formulario de la primera pestaña (Remate)."""
        logger.info("Extrayendo datos base de la pestaña 'Remate'...")
        
        # Mapeo usando normalize-space() para evitar fallos por espacios o saltos de línea ocultos.
        # Nota: Se mantiene 'Jurisdisccional' si es un error de tipeo real en la web del estado.
        fields = {
            "Expediente": "//div[normalize-space(text())='Expediente']/following-sibling::div",
            "Distrito Judicial": "//div[normalize-space(text())='Distrito Judicial']/following-sibling::div",
            "Órgano Jurisdiccional": "//div[normalize-space(text())='Órgano Jurisdisccional']/following-sibling::div",
            "Instancia": "//div[normalize-space(text())='Instancia']/following-sibling::div",
            "Juez": "//div[normalize-space(text())='Juez']/following-sibling::div",
            "Especialista": "//div[normalize-space(text())='Especialista']/following-sibling::div",
            "Materia": "//div[normalize-space(text())='Materia']/following-sibling::div",
            "Resolución": "//div[normalize-space(text())='Resolución']/following-sibling::div",
            "Fecha Resolución": "//div[normalize-space(text())='Fecha Resolución']/following-sibling::div",
            "Convocatoria": "//div[normalize-space(text())='Convocatoria']/following-sibling::div",
            "Tasación": "//div[normalize-space(text())='Tasación']/following-sibling::div",
            "Precio Base": "//div[normalize-space(text())='Precio Base']/following-sibling::div",
            "Incremento entre ofertas": "//div[normalize-space(text())='Incremento entre ofertas']/following-sibling::div",
            "Arancel": "//div[normalize-space(text())='Arancel']/following-sibling::div",
            "Oblaje": "//div[normalize-space(text())='Oblaje']/following-sibling::div"
        }
        
        data = {}
        for key, xpath in fields.items():
            data[key] = await self._get_text_by_xpath(xpath)

        # Usando un XPath más robusto para la descripción, evitando los IDs dinámicos de PrimeFaces (j_idt)
        xpath_desc = "//label[contains(text(), 'Descripción')]/following-sibling::div | //div[contains(@id, 'tvResumen')]//span[contains(@class, 'descripcion')]"
        data["Descripción"] = await self._get_text_by_xpath(xpath_desc)
        
        logger.info("Extracción de tab 'Remate' completada exitosamente.")
        return data

    async def download_resolucion_pdf(self, test_mode: bool = False) -> io.BytesIO:
        """
        Intercepta y descarga el PDF de resolución real (sin usar mocks en producción).
        :param test_mode: Si es True, inyecta un mock en BytesIO para pruebas unitarias.
        """
        logger.info("Ejecutando intercepción del PDF de resolución...")
        
        if test_mode:
            return io.BytesIO(b"%PDF-1.4 Mock Dummy PDF Fallback\nEOF")
        
        # 1. Crear un directorio temporal para la descarga
        temp_dir = tempfile.mkdtemp()
        
        try:
            # 2. Configurar el comportamiento de descarga en el navegador vía CDP
            await self.page.send(
                browser_cdp.set_download_behavior(
                    behavior="allow",
                    download_path=temp_dir,
                    events_enabled=True
                )
            )
            
            # 3. Click en el botón de PDF usando un selector robusto (no IDs dinámicos)
            success = await self._click_by_xpath("//button[contains(@class, 'ui-button') and contains(.//span, 'Resolución')]")
            if not success:
                # Fallback por si el texto varía
                success = await self._click_by_xpath("//button[contains(@title, 'PDF') or contains(@title, 'Descargar')]")
                
            if not success:
                raise RemajuExtractorError("Botón de descarga de resolución PDF no encontrado en el DOM.")
            
            # 4. Polling para esperar que el archivo termine de descargar (evitando .crdownload)
            downloaded_file = None
            for _ in range(30):  # Máximo 15 segundos
                files = os.listdir(temp_dir)
                pdfs = [f for f in files if f.endswith('.pdf')]
                # Asegurarnos de que no hay descargas activas (.crdownload)
                crdownloads = [f for f in files if f.endswith('.crdownload')]
                
                if pdfs and not crdownloads:
                    downloaded_file = os.path.join(temp_dir, pdfs[0])
                    break
                await asyncio.sleep(0.5)
            
            if not downloaded_file:
                raise RemajuExtractorError("Timeout esperando la descarga del PDF real.")
                
            # 5. Cargar a memoria
            pdf_bytes = Path(downloaded_file).read_bytes()
            return io.BytesIO(pdf_bytes)
            
        finally:
            # 6. Limpiar sistema de archivos
            for f in os.listdir(temp_dir):
                try:
                    os.remove(os.path.join(temp_dir, f))
                except Exception:
                    pass
            try:
                os.rmdir(temp_dir)
            except Exception:
                pass

    async def extract_tab_inmuebles(self) -> list:
        """Cambia a la pestaña Inmuebles, espera el estado e itera la grilla extrayendo columnas sin IDs dinámicos."""
        logger.info("Navegando a la pestaña 'Inmuebles'...")
        
        success = await self._click_by_xpath("//ul[@role='tablist']//a[text()='Inmuebles']")
        if not success:
            raise RemajuExtractorError("Error al hacer click en la pestaña 'Inmuebles'.")
            
        await self._wait_for_spinner_to_disappear()
        
        inmuebles = []
        rows = await self.page.select_all('[id$="dtResumenInmueble_data"] tr[data-ri]')
        
        for row in rows:
            try:
                tds = await row.select_all("td")
                if len(tds) < 4: # Necesitamos al menos 4 columnas para partida, tipo, dir y cargas
                    continue
                    
                # Extraemos las propiedades de manera segura, iterando los TDs en lugar de usar selectores internos.
                partida = getattr(tds[0], 'text', "")
                tipo_inm = getattr(tds[1], 'text', "")
                direccion = getattr(tds[2], 'text', "")
                carga = getattr(tds[3], 'text', "")
                
                # Saneamiento rápido de tipos si la evaluación falla
                partida = partida if isinstance(partida, str) else ""
                tipo_inm = tipo_inm if isinstance(tipo_inm, str) else ""
                direccion = direccion if isinstance(direccion, str) else ""
                carga = carga if isinstance(carga, str) else ""
                
                inmuebles.append({
                    "partida": partida.strip(),
                    "tipo": tipo_inm.strip(),
                    "direccion": direccion.strip(),
                    "carga_gravamen": carga.strip()
                })
            except Exception as e:
                logger.error(f"Error parseando una fila de inmueble: {e}")
                continue
                
        return inmuebles

    async def extract_tab_cronograma(self) -> dict:
        """Aísla y extrae estrictamente las fechas de la fase de 'Publicación e Inscripcion'."""
        logger.info("Navegando a la pestaña 'Cronograma'...")
        
        success = await self._click_by_xpath("//ul[@role='tablist']//a[text()='Cronograma']")
        if not success:
            raise RemajuExtractorError("Error al hacer click en la pestaña 'Cronograma'.")
            
        await self._wait_for_spinner_to_disappear()
        
        rows = await self.page.select_all('[id$="dtCronograma_data"] tr')
        
        for row in rows:
            try:
                tds = await row.select_all("td")
                if not tds or len(tds) < 3:
                    continue
                    
                fase = getattr(tds[0], 'text', "")
                fase = fase if isinstance(fase, str) else ""
                fase = fase.strip()
                
                if fase == "Publicación e Inscripcion":
                    fecha_ini = getattr(tds[1], 'text', "")
                    fecha_ini = fecha_ini if isinstance(fecha_ini, str) else ""
                    fecha_fin = getattr(tds[2], 'text', "")
                    fecha_fin = fecha_fin if isinstance(fecha_fin, str) else ""
                    
                    return {
                        "fase": fase,
                        "fecha_inicio": fecha_ini.strip(),
                        "fecha_fin": fecha_fin.strip()
                    }
            except Exception as e:
                logger.error(f"Error parseando fila del cronograma: {e}")
                continue
                
        logger.warning("Fase 'Publicación e Inscripcion' no encontrada en el cronograma.")
        return {}

    async def return_to_search(self) -> bool:
        """Cierra el ciclo de la ficha validando el retorno exitoso a la bandeja de remates."""
        logger.info("Ejecutando retorno a la bandeja de búsqueda general...")
        
        success = await self._click_by_xpath("//button[contains(@class, 'ui-button')]//span[text()='Regresar']/..")
        if not success:
            logger.error("No se localizó el botón 'Regresar' en el DOM.")
            return False
            
        await self._wait_for_spinner_to_disappear()
        
        current_url = await self.page.evaluate("window.location.href")
        target_url = f"{self.config['url_base']}{self.config['url_search_path']}"
        
        if target_url in current_url:
            logger.info("Retorno seguro completado con éxito.")
            return True
            
        logger.error(f"Fallo en el retorno. URL actual: {current_url}")
        return False