# src/main.py
import asyncio
import logging
import nodriver as uc

# Importación de módulos reales alineados estrictamente al árbol de carpetas rígido congelado del proyecto
from src.core.storage.history_manager import RemajuHistoryManager
from src.auth.login_handler import RemajuAuthenticator
from src.scraper.search import RemajuSearchScraper

# Configuración global de logging para el orquestador principal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Iniciando bot orquestador asíncrono lineal para REMAJU...")
    
    # 1. Instanciar RemajuHistoryManager apuntando al archivo de persistencia atómica en la raíz
    history_manager = RemajuHistoryManager("historial_procesados.json")
    
    # 2. Inicializar el navegador asíncrono nativo con la última versión de nodriver
    logger.info("Iniciando instancia automatizada de nodriver...")
    browser = await uc.start()
    
    # nodriver abre una pestaña por defecto de forma automática al iniciar el navegador
    page = browser.main_tab
    
    try:
        # 3. Instanciar RemajuAuthenticator y ejecutar el inicio de sesión directo con ddddocr
        authenticator = RemajuAuthenticator(page)
        logger.info("Ejecutando proceso de autenticación automatizado con resolución local...")
        login_success = await authenticator.execute_login()
        
        if not login_success:
            logger.error("Autenticación fallida o captchas incorrectos agotados. Abortando flujo.")
            return
            
        logger.info("Autenticación completada exitosamente. Bot situado en inicio.xhtml")
        
        # 4. Instanciar RemajuSearchScraper inyectando el gestor de historial de producción
        search_scraper = RemajuSearchScraper(page, history_manager=history_manager)
        logger.info("Navegando al módulo de búsqueda de remates de PrimeFaces...")
        
        success_nav = await search_scraper.navigate_to_search_module()
        if not success_nav:
            logger.error("No se pudo confirmar la carga de la bandeja de búsqueda. Abortando.")
            return
        
        # 5. Bucle Principal de la Rutina Diaria del Paginador
        page_index = 1
        while True:
            logger.info(f"=== Procesando Bandeja de Resultados de REMAJU - Página #{page_index} ===")
            
            # Ejecuta la iteración cíclica de la grilla exterior y la delegación interna de extracción
            processed_cards = await search_scraper.process_grid_cards()
            logger.info(f"Página #{page_index} finalizada. Remates ingresados a la bitácora: {processed_cards}")
            
            # Gestionar el paginador global para avanzar en la rutina diaria de la bandeja
            logger.info(f"Evaluando existencia de páginas subsecuentes para la página #{page_index}...")
            has_next_page = await search_scraper.handle_pagination()
            
            if not has_next_page:
                logger.info("Fin de registros alcanzado. El paginador no reporta más páginas disponibles.")
                break
                
            page_index += 1
            # Pausa de estabilización del ciclo de vida del servidor JSF entre páginas
            await asyncio.sleep(2.0)
            
        logger.info("Orquestación completada de punta a punta de forma exitosa.")
        
    except Exception as e:
        logger.error(f"Error crítico en la ejecución del orquestador principal main.py: {e}")
    finally:
        # 6. Cerrar el navegador asíncrono de forma segura y liberar la memoria del sistema
        logger.info("Cerrando sesión del navegador asíncrono de forma segura...")
        try:
            if 'browser' in locals() and browser:
                # Método de cierre síncrono definitivo expuesto por nodriver
                browser.stop()
        except Exception as e:
            logger.error(f"Error al detener la instancia del navegador: {e}")
        logger.info("Proceso de bot REMAJU finalizado de forma limpia.")

if __name__ == "__main__":
    # Invocación de la rutina asíncrona del orquestador principal
    asyncio.run(main())
