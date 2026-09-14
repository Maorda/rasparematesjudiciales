# src/scraper/search.py
import asyncio
import json
import logging
from pathlib import Path

# Configuración básica de logging para auditoría de la grilla interna
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RemajuSearchError(Exception):
    """Excepción personalizada para errores críticos en el módulo de búsqueda y filtrado."""
    pass

class RemajuSearchScraper:
    def __init__(self, page, creds_path: str = "autenticacion.json", history_manager=None):
        """
        Inicializa el scraper de búsqueda y filtrado perimetral.
        :param page: Objeto de página de nodriver.
        :param creds_path: Ruta al archivo JSON de credenciales/configuración.
        :param history_manager: Instancia para control de persistencia histórica.
        """
        self.page = page
        self.creds_path = Path(creds_path)
        self.history_manager = history_manager
        # Cargamos la configuración una sola vez al instanciar para evitar I/O redundante
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Carga y valida la configuración fragmentada de URLs desde el archivo JSON."""
        if not self.creds_path.exists():
            logger.error(f"Archivo de configuración no encontrado: {self.creds_path}")
            raise FileNotFoundError(f"Archivo de configuración no encontrado: {self.creds_path}")
        
        with open(self.creds_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            required_keys = ["url_base", "url_search_path", "url_detail_path"]
            if not all(k in data for k in required_keys):
                raise ValueError(f"El JSON debe contener las llaves exactas: {required_keys}")
            return data

    async def _wait_for_spinner_to_disappear(self):
        """
        Espera activamente a que el spinner 'dlgEstado' desaparezca del DOM.
        Se usa evaluación JS para evitar excepciones de elementos no encontrados.
        """
        logger.info("Esperando que el spinner 'dlgEstado' desaparezca...")
        for _ in range(40):  # Timeout máximo de 20 segundos (40 iteraciones * 0.5s)
            is_visible = await self.page.evaluate("""
                () => {
                    const el = document.getElementById('dlgEstado');
                    return el ? window.getComputedStyle(el).display !== 'none' : false;
                }
            """)
            if not is_visible:
                logger.info("Spinner oculto.")
                await asyncio.sleep(0.5)
                return
            await asyncio.sleep(0.5)
        
        logger.warning("Tiempo de espera agotado para el spinner. Continuando flujo...")

    async def navigate_to_search_module(self) -> bool:
        """Navega por el menú acordeón hasta la vista de búsqueda de remates oficial."""
        target_search_url = f"{self.config['url_base']}{self.config['url_search_path']}"

        logger.info("Localizando acordeón 'REMATES JUDICIALES'...")
        accordion = await self.page.find("REMATES JUDICIALES")
        if accordion:
            await accordion.click()
            await asyncio.sleep(0.5)

        logger.info("Seleccionando submenú interactivo 'BUSCAR REMATES'...")
        submenu = await self.page.select("[id='menuForm:j_idt76']")
        if submenu:
            await submenu.click()

        await self._wait_for_spinner_to_disappear()

        current_url = await self.page.evaluate("window.location.href")
        if target_search_url in current_url:
            logger.info("¡Navegación al módulo de búsqueda confirmada!")
            return True
        
        logger.error(f"Fallo en la navegación. URL actual: {current_url}")
        return False

    async def process_grid_cards(self) -> int:
        """
        Procesa las tarjetas de remate de la grilla actual aplicando filtros perimetrales,
        control histórico de duplicados y cortocircuito para 'Pago por alimentos'.
        """
        target_detail_url = f"{self.config['url_base']}{self.config['url_detail_path']}"
        processed_count = 0

        grid_container = await self.page.select("[id='formBuscarRematesPublicados:listaRemate_content']")
        if not grid_container:
            logger.warning("No se encontró el contenedor de la grilla principal de remates.")
            return 0

        # En lugar de guardar los objetos de las tarjetas, contamos cuántas hay.
        # Esto previene el error "Stale DOM" cuando navegamos al detalle y luego regresamos a la grilla.
        cards = await self.page.select_all("[id*='formBuscarRematesPublicados:listaRemate:']")
        total_cards = len(cards) if cards else 0

        if total_cards == 0:
            logger.warning("No se encontraron tarjetas de remate en la grilla actual.")
            return 0

        for index in range(total_cards):
            logger.info(f"Analizando tarjeta de remate índice {index}...")
            
            # Re-capturamos los elementos en cada iteración asegurando un DOM fresco
            exp_selector = f"[id='formBuscarRematesPublicados:listaRemate:{index}:j_idt203_content'] .label-danger"
            exp_text_elem = await self.page.select(exp_selector)
            
            raw_title = await exp_text_elem.get_text() if exp_text_elem else ""
            if "REMATE N°" in raw_title and " - " in raw_title:
                parts = raw_title.split(" - ")
                numero_expediente = parts[0].strip()
                numero_convocatoria = parts[1].strip()
            else:
                numero_expediente = f"EXP-FALLBACK-{index}"
                numero_convocatoria = "PRIMERA CONVOCATORIA"

            # Control de Duplicados Históricos
            if self.history_manager and self.history_manager.is_processed(numero_expediente, numero_convocatoria):
                logger.info(f"Expediente {numero_expediente} ({numero_convocatoria}) ya procesado. Omitiendo click.")
                continue

            # Ingresar al detalle
            btn_detalle = await self.page.select(f"[id='formBuscarRematesPublicados:listaRemate:{index}:j_idt237']")
            if btn_detalle:
                await btn_detalle.click()
                await self._wait_for_spinner_to_disappear()

            # Validación de entrada a la ficha de detalle
            current_url = await self.page.evaluate("window.location.href")
            if target_detail_url in current_url:
                logger.info("Ficha de detalle cargada en el DOM. Evaluando campo 'Materia'...")
                
                materia_elem = await self.page.select("//div[text()='Materia']/following-sibling::div")
                materia_text = await materia_elem.get_text() if materia_elem else ""
                materia_text = materia_text.strip()

                # Cortocircuito: Alimentos
                if materia_text == "Pago por alimentos":
                    logger.info("Cortocircuito activado: Materia 'Pago por alimentos'. Abortando y regresando.")
                else:
                    logger.info(f"Materia apta para ingesta ({materia_text}). Autorizando extracción...")
                    # TODO: Aquí inyectarás tu módulo de extracción profunda (precios, tasación, fechas).
                    
                # Siempre debemos regresar a la grilla para que el loop continúe correctamente
                btn_regresar = await self.page.select("//button[contains(@class, 'ui-button')]//span[text()='Regresar']/..")
                if btn_regresar:
                    await btn_regresar.click()
                    await self._wait_for_spinner_to_disappear()
                    
                processed_count += 1

        return processed_count

    async def handle_pagination(self) -> bool:
        """Orquestador del paginador PrimeFaces para avanzar a la siguiente página."""
        paginator_next = await self.page.select("[id='formBuscarRematesPublicados:listaRemate_paginator_bottom'] .ui-paginator-next")
        
        if paginator_next:
            is_disabled = await self.page.evaluate("""
                (el) => el.classList.contains('ui-state-disabled')
            """, paginator_next)
            
            if is_disabled:
                logger.info("Se ha alcanzado la última página del paginador de REMAJU.")
                return False

            await paginator_next.click()
            await self._wait_for_spinner_to_disappear()
            return True
        
        logger.info("No se encontró el componente de paginación en el DOM actual.")
        return False