# tests/test_search.py
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, mock_open, MagicMock
from src.scraper.search import RemajuSearchScraper, RemajuSearchError

@pytest.fixture
def mock_nodriver_page():
    """Fixture asíncrono para simular de forma resiliente el objeto de página de nodriver."""
    page = AsyncMock()
    mock_element = AsyncMock()
    page.find.return_value = mock_element
    page.select.return_value = mock_element
    page.select_all.return_value = [mock_element]
    return page

@pytest.fixture
def valid_config_json():
    """Fixture con el contrato fragmentado real e institucional de REMAJU."""
    return json.dumps({
        "url_base": "https://remaju.pj.gob.pe/remaju",
        "url_search_path": "/pages/inscripcion/bandejaBuscarRematesPublicados.xhtml",
        "url_detail_path": "/pages/remate/detalle/mostrarDetalleRemate.xhtml"
    })

@pytest.fixture
def mock_history_manager():
    """Fixture simulando el gestor histórico de persistencia local."""
    manager = MagicMock()
    manager.is_processed.return_value = False
    return manager


# --- CASOS DE PRUEBA ---

@pytest.mark.asyncio
async def test_load_config_missing_keys(mock_nodriver_page):
    """Prueba que se lance ValueError si faltan llaves obligatorias en el archivo de configuración."""
    incomplete_json = json.dumps({"url_base": "https://remaju.pj.gob.pe/remaju"})

    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=incomplete_json)):
        with pytest.raises(ValueError, match="El JSON debe contener las llaves exactas"):
            # Ahora falla directo en el constructor ya que _load_config se llama en el __init__
            RemajuSearchScraper(mock_nodriver_page)

@pytest.mark.asyncio
async def test_navigation_to_search_success(mock_nodriver_page, valid_config_json):
    """Prueba 1: Navegación correcta del menú acordeón y validación de URL compuesta."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_config_json)), \
         patch("src.scraper.search.asyncio.sleep", new_callable=AsyncMock):
        
        scraper = RemajuSearchScraper(mock_nodriver_page)

        def evaluate_stub(script, *args, **kwargs):
            if "dlgEstado" in script:
                return False
            # Debe retornar la ruta esperada para pasar el check del if
            return "https://remaju.pj.gob.pe/remaju/pages/inscripcion/bandejaBuscarRematesPublicados.xhtml"

        mock_nodriver_page.evaluate.side_effect = evaluate_stub

        result = await scraper.navigate_to_search_module()
        assert result is True
        mock_nodriver_page.find.assert_any_call("REMATES JUDICIALES")
        mock_nodriver_page.select.assert_any_call("[id='menuForm:j_idt76']")

@pytest.mark.asyncio
async def test_grid_card_skip_if_processed(mock_nodriver_page, valid_config_json, mock_history_manager):
    """Prueba 2: Descarte rápido perimetral de tarjeta exterior si el expediente ya consta en el histórico."""
    mock_history_manager.is_processed.return_value = True

    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_config_json)):
         
        scraper = RemajuSearchScraper(mock_nodriver_page, history_manager=mock_history_manager)

        mock_title_element = AsyncMock()
        mock_title_element.get_text = AsyncMock(return_value="REMATE N° 25243 - PRIMERA CONVOCATORIA")
        
        # Simulamos que hay 1 tarjeta en la grilla y luego extraemos su título
        mock_nodriver_page.select_all.return_value = [AsyncMock()] 
        
        def page_select_stub(selector):
            if "listaRemate_content" in selector:
                return AsyncMock()
            if "label-danger" in selector:
                return mock_title_element
            return None

        mock_nodriver_page.select.side_effect = page_select_stub

        processed = await scraper.process_grid_cards()
        assert processed == 0
        mock_history_manager.is_processed.assert_called_once_with("REMATE N° 25243", "PRIMERA CONVOCATORIA")

@pytest.mark.asyncio
async def test_alimony_short_circuit(mock_nodriver_page, valid_config_json, mock_history_manager):
    """Prueba 3: Activación de cortocircuito (click en 'Regresar') al detectar 'Pago por alimentos'."""
    mock_history_manager.is_processed.return_value = False

    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_config_json)):

        scraper = RemajuSearchScraper(mock_nodriver_page, history_manager=mock_history_manager)

        mock_title_element = AsyncMock()
        mock_title_element.get_text = AsyncMock(return_value="REMATE N° 25243 - PRIMERA CONVOCATORIA")
        
        materia_elem = AsyncMock()
        materia_elem.get_text = AsyncMock(return_value="Pago por alimentos")

        mock_btn_detalle = AsyncMock()
        mock_btn_regresar = AsyncMock()

        # Simulación de la lista de tarjetas y sus nodos dinámicos
        mock_nodriver_page.select_all.return_value = [AsyncMock()]

        def page_select_stub(selector):
            if "listaRemate_content" in selector:
                return AsyncMock() 
            if "label-danger" in selector:
                return mock_title_element
            if "j_idt237" in selector:  # Botón detalle
                return mock_btn_detalle
            if "Materia" in selector:
                return materia_elem
            if "Regresar" in selector:
                return mock_btn_regresar
            return None 

        mock_nodriver_page.select.side_effect = page_select_stub

        def evaluate_stub(script, *args, **kwargs):
            if "dlgEstado" in script:
                return False
            return "https://remaju.pj.gob.pe/remaju/pages/remate/detalle/mostrarDetalleRemate.xhtml"

        mock_nodriver_page.evaluate.side_effect = evaluate_stub

        processed = await scraper.process_grid_cards()
        
        # El conteo pasa de 0 a 1 porque el flujo terminó (alimentos o no, el bloque se procesó y regresó)
        # Nota: La lógica dice "processed_count += 1" al final de la iteración.
        assert processed == 1
        mock_btn_regresar.click.assert_called_once()

@pytest.mark.asyncio
async def test_paginator_next_page(mock_nodriver_page, valid_config_json):
    """Prueba 4: Avance e iteración asíncrona controlada del paginador PrimeFaces de REMAJU."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_config_json)):
         
        scraper = RemajuSearchScraper(mock_nodriver_page)

        mock_paginator = AsyncMock()
        mock_nodriver_page.select.return_value = mock_paginator

        def evaluate_stub(script, *args, **kwargs):
            if "classList" in script:
                return False  
            if "dlgEstado" in script:
                return False
            return ""

        mock_nodriver_page.evaluate.side_effect = evaluate_stub

        res = await scraper.handle_pagination()
        assert res is True
        mock_paginator.click.assert_called_once()