# tests/test_auth.py
import pytest
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, mock_open, MagicMock
from src.auth.login_handler import RemajuAuthenticator, RemajuAuthError

# --- FIXTURES ---

@pytest.fixture
def mock_nodriver_page():
    """Mock asíncrono avanzado para simular de forma resiliente el objeto de página de nodriver."""
    page = AsyncMock()
    
    mock_element = AsyncMock()
    page.find.return_value = mock_element
    
    mock_input = AsyncMock()
    page.select.return_value = mock_input
    
    return page

@pytest.fixture
def valid_json_data():
    """Fixture con el contrato dinámico fragmentado oficial de la plataforma."""
    return json.dumps({
        "usuario": "12345678", 
        "clave": "Secreta123*",
        "url_base": "https://pj.gob.pe",
        "url_login_path": "/pages/seguridad/login.xhtml"
    })


# --- CASOS DE PRUEBA ---

@pytest.mark.asyncio
async def test_load_credentials_file_not_found(mock_nodriver_page):
    """Prueba 1: Manejo de error si el archivo de credenciales no existe."""
    with patch("ddddocr.DdddOcr", return_value=MagicMock()):
        authenticator = RemajuAuthenticator(mock_nodriver_page, creds_path="fake.json")
    
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(FileNotFoundError, match="Archivo de credenciales no encontrado"):
            authenticator.load_credentials()

@pytest.mark.asyncio
async def test_load_credentials_invalid_json_keys(mock_nodriver_page):
    """Prueba 1.1: Manejo de error si faltan claves obligatorias en el contrato fragmentado."""
    with patch("ddddocr.DdddOcr", return_value=MagicMock()):
        authenticator = RemajuAuthenticator(mock_nodriver_page)
    incomplete_json = json.dumps({"usuario": "12345678"}) 

    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=incomplete_json)), \
         patch("ddddocr.DdddOcr", return_value=MagicMock()):
        
        with pytest.raises(ValueError, match="El JSON debe contener las claves exactas"):
            authenticator.load_credentials()

@pytest.mark.asyncio
async def test_initial_navigation_and_modal(mock_nodriver_page, valid_json_data):
    """Prueba 2: Simulación de navegación dinámica leyendo la imagen captcha.png real de la raíz."""
    # Instanciamos ddddocr de verdad para esta prueba para validar que procese la imagen física correctamente
    authenticator = RemajuAuthenticator(mock_nodriver_page)

    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_json_data)), \
         patch("src.auth.login_handler.asyncio.sleep", new_callable=AsyncMock): 

        config = json.loads(valid_json_data)
        absolute_target_url = f"{config['url_base']}{config['url_login_path']}"
        success_url = f"{config['url_base']}/pages/inicio.xhtml"

        def evaluate_stub(script, *args, **kwargs):
            if "dlgEstado" in script:
                return False 
            return success_url 

        mock_nodriver_page.evaluate.side_effect = evaluate_stub

        # Simulamos save_screenshot leyendo el archivo físico real captcha.png de tu raíz
        captcha_path = Path("captcha.png")
        if captcha_path.exists():
            with open(captcha_path, "rb") as f:
                real_captcha_bytes = f.read()
        else:
            real_captcha_bytes = b"bytes_de_respaldo_si_el_archivo_no_existe"

        mock_nodriver_page.select.return_value.save_screenshot = AsyncMock(return_value=real_captcha_bytes)

        result = await authenticator.execute_login()
        
        assert result is True
        mock_nodriver_page.get.assert_called_once_with(absolute_target_url)
        assert mock_nodriver_page.find.call_count >= 2 
        assert mock_nodriver_page.select.call_count >= 3

@pytest.mark.asyncio
async def test_captcha_success_third_attempt(mock_nodriver_page, valid_json_data):
    """Prueba 3: Simulación adaptativa al bucle JSF. Éxito al 3er intento consumiendo captcha.png."""
    authenticator = RemajuAuthenticator(mock_nodriver_page)
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_json_data)), \
         patch("src.auth.login_handler.asyncio.sleep", new_callable=AsyncMock):
        
        config = json.loads(valid_json_data)
        absolute_target_url = f"{config['url_base']}{config['url_login_path']}"
        success_url = f"{config['url_base']}/pages/inicio.xhtml"
        
        attempt_counter = 0

        def evaluate_stub(script, *args, **kwargs):
            nonlocal attempt_counter
            if "dlgEstado" in script:
                return False
            
            attempt_counter += 1
            if attempt_counter < 3:
                return absolute_target_url 
            return success_url 

        mock_nodriver_page.evaluate.side_effect = evaluate_stub

        # Carga dinámica del archivo físico de la raíz para inyectar en memoria del mock
        captcha_path = Path("captcha.png")
        real_captcha_bytes = captcha_path.read_bytes() if captcha_path.exists() else b"fallback"
        mock_nodriver_page.select.return_value.save_screenshot = AsyncMock(return_value=real_captcha_bytes)
        
        result = await authenticator.execute_login()
        assert result is True
        assert mock_nodriver_page.select.call_count >= 9

@pytest.mark.asyncio
@patch('src.auth.login_handler.asyncio.sleep', new_callable=AsyncMock)
async def test_captcha_failure_max_retries_sleeps(mock_sleep, mock_nodriver_page, valid_json_data):
    """Prueba 4: Bloqueo de seguridad tras 5 fallos continuos consumiendo la imagen física de control."""
    authenticator = RemajuAuthenticator(mock_nodriver_page)
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_json_data)):
        
        config = json.loads(valid_json_data)
        absolute_target_url = f"{config['url_base']}{config['url_login_path']}"
        
        def evaluate_stub(script, *args, **kwargs):
            if "dlgEstado" in script:
                return False
            return absolute_target_url 

        mock_nodriver_page.evaluate.side_effect = evaluate_stub
        
        captcha_path = Path("captcha.png")
        real_captcha_bytes = captcha_path.read_bytes() if captcha_path.exists() else b"fallback"
        mock_nodriver_page.select.return_value.save_screenshot = AsyncMock(return_value=real_captcha_bytes)
        
        with pytest.raises(RemajuAuthError, match="Límite de intentos de captcha agotado"):
            await authenticator.execute_login()
            
        mock_sleep.assert_any_call(120)
