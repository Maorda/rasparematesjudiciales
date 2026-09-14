# src/auth/login_handler.py
import asyncio
import json
import logging
from pathlib import Path
import ddddocr  # Librería local y offline para resolución de captcha

# Configuración básica de logging para auditoría del bot
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RemajuAuthError(Exception):
    """Excepción personalizada para errores críticos de autenticación en REMAJU."""
    pass

class RemajuAuthenticator:
    def __init__(self, page, creds_path: str = "autenticacion.json"):
        """
        Inicializa el handler de autenticación asíncrono.
        :param page: Objeto de página de nodriver.
        :param creds_path: Ruta al archivo JSON de credenciales de la raíz.
        """
        self.page = page
        self.creds_path = Path(creds_path)
        self.max_retries = 5
        self.lock_timeout = 120  # Segundos de bloqueo exigidos

        # Inicialización única de la red neuronal ddddocr con publicidad desactivada
        self.ocr = ddddocr.DdddOcr(show_ad=False)

    def load_credentials(self) -> dict:
        """Carga y valida el archivo de credenciales local verificando el contrato fragmentado."""
        if not self.creds_path.exists():
            logger.error(f"Archivo no encontrado: {self.creds_path}")
            raise FileNotFoundError(f"Archivo de credenciales no encontrado: {self.creds_path}")
        
        with open(self.creds_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if "usuario" not in data or "clave" not in data or "url_base" not in data or "url_login_path" not in data:
                raise ValueError("El JSON debe contener las claves exactas 'usuario', 'clave', 'url_base' y 'url_login_path'.")
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
                logger.info("Spinner de la plataforma oculto.")
                await asyncio.sleep(0.5)
                return
            await asyncio.sleep(0.5)
        
        logger.warning("Tiempo de espera agotado para el spinner. Continuando flujo...")

    async def resolve_captcha(self, captcha_element) -> str:
        """
        Captura el elemento de imagen de nodriver en formato bytes y lo procesa de forma local.
        """
        if not captcha_element:
            logger.error("El elemento de imagen del captcha no fue encontrado en el DOM.")
            return ""

        logger.info("Procesando captcha localmente con ddddocr...")
        try:
            # Obtención de bytes nativos asíncronos en memoria sin tocar disco
            image_bytes = await captcha_element.save_screenshot()
            
            # Clasificación local de la red neuronal offline
            text_result = self.ocr.classification(image_bytes)
            logger.info(f"Texto del captcha clasificado con éxito: {text_result}")
            return str(text_result).strip()
        except Exception as e:
            logger.error(f"Error durante el procesamiento local de ddddocr: {str(e)}")
            return ""

    async def execute_login(self) -> bool:
        """Flujo principal asíncrono de autenticación ingresando dinámicamente desde la URL del JSON."""
        creds = self.load_credentials()

        # Ensamblaje dinámico y seguro de las cadenas de dirección web
        target_login_url = f"{creds['url_base']}{creds['url_login_path']}"

        logger.info(f"Navegando a la dirección web ensamblada: {target_login_url}")
        await self.page.get(target_login_url)

        # 2. Control de latencia inicial de carga de página
        await self._wait_for_spinner_to_disappear()

        logger.info("Esperando 3 segundos para asegurar la carga completa y transiciones del modal legal...")
        await asyncio.sleep(3.0)

        # 3. Cerrar Modal Legal de Indicaciones de REMAJU
        logger.info("Verificando existencia de modal legal...")
        try:
            btn_aceptar = await asyncio.wait_for(self.page.find("Aceptar"), timeout=5.0)
            await btn_aceptar.click()
            logger.info("Modal legal cerrado con éxito.")
            await asyncio.sleep(1) 
        except (asyncio.TimeoutError, Exception):
            logger.warning("No se pudo interactuar con el modal legal o no apareció. Continuando flujo...")

        # 4. Bucle de Control del Captcha e Inyección (Algoritmo Rígido adaptado a PrimeFaces)
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"Intento de inicio de sesión {attempt}/{self.max_retries}...")
            
            logger.info("Seleccionando e inyectando credenciales en el formulario...")
            btn_con_casilla = await self.page.find("Con Casilla")
            if btn_con_casilla:
                await btn_con_casilla.click()

            txt_usuario = await self.page.select("[id='frmLogin:usuario']")
            await txt_usuario.click()
            await txt_usuario.send_keys(creds["usuario"])

            # Al refrescar la vista por fallo en captcha, JSF limpia obligatoriamente la clave
            txt_clave = await self.page.select("[id='frmLogin:claveConCasilla']")
            await txt_clave.click()
            await txt_clave.send_keys(creds["clave"])
            
            # Localizar de manera tolerante la imagen dinámica del captcha
            captcha_img_element = await self.page.select("img.captcha-image-fix")
            if not captcha_img_element:
                 captcha_img_element = await self.page.select("[id='frmLogin:captcha_image']")
            
            # Invocar la resolución local de ddddocr
            captcha_text = await self.resolve_captcha(captcha_img_element)
            
            # Inyectar el resultado resuelto
            txt_captcha_input = await self.page.select("[id='frmLogin:captcha']")
            await txt_captcha_input.click()
            await txt_captcha_input.send_keys(captcha_text)

            btn_submit = await self.page.select("[id='frmLogin:btnIngresar']") 
            if not btn_submit:
                 btn_submit = await self.page.find("Iniciar Sesión")
            await btn_submit.click()

            # Esperar el procesamiento asíncrono del servidor antes de evaluar la URL
            await self._wait_for_spinner_to_disappear()

            # Validar si el árbol de componentes redirigió a la vista xhtml interna de éxito
            current_url = await self.page.evaluate("window.location.href")
            if "inicio.xhtml" in current_url:
                logger.info("¡Autenticación exitosa! Redirección a inicio.xhtml confirmada.")
                return True
            
            logger.warning("Fallo en la autenticación (captcha incorrecto). El formulario se ha limpiado.")

        # 5. Activación obligatoria del candado de tiempo si se agotan las oportunidades
        logger.error(f"Límite de {self.max_retries} intentos alcanzado. Aplicando bloqueo de seguridad de {self.lock_timeout}s.")
        await asyncio.sleep(self.lock_timeout)
        raise RemajuAuthError("Error crítico: Límite de intentos de captcha agotado. Bloqueo de seguridad activado.")
