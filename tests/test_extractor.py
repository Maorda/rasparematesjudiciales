# tests/test_extractor.py
import pytest
import asyncio
import json
import io
from pathlib import Path
from unittest.mock import AsyncMock, patch, mock_open, PropertyMock, MagicMock
from src.scraper.extractor import RemajuExtractorScraper, RemajuExtractorError

@pytest.fixture
def mock_nodriver_page():
    """Fixture que simula el objeto de página de nodriver de forma asíncrona."""
    page = AsyncMock()
    page.evaluate.return_value = ""
    page.select.return_value = AsyncMock()
    page.select_all.return_value = []
    page.send = AsyncMock() # Simular canal CDP de red
    return page

@pytest.fixture
def valid_config_json():
    """Contrato fragmentado de configuración REMAJU."""
    return json.dumps({
        "url_base": "https://remaju.pj.gob.pe/remaju",
        "url_search_path": "/pages/inscripcion/bandejaBuscarRematesPublicados.xhtml",
        "url_detail_path": "/pages/remate/detalle/mostrarDetalleRemate.xhtml"
    })

def create_mock_td(text_value):
    """Helper de arquitectura para instanciar TDs limpios con propiedades fijas de texto."""
    td = MagicMock()
    type(td).text = PropertyMock(return_value=text_value)
    return td

# --- CASOS DE PRUEBA ---

@pytest.mark.asyncio
async def test_extract_tab_remate_base_data(mock_nodriver_page, valid_config_json):
    """Prueba 1: Extracción de textos mediante XPaths seguros (normalize-space) en el tab Remate."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_config_json)):
        
        scraper = RemajuExtractorScraper(mock_nodriver_page)
        
        def evaluate_stub(script, *args, **kwargs):
            if "Expediente" in script: return "00123-2026-0-1801-JR-CI-01"
            if "Juez" in script: return "JUAN PEREZ"
            if "j_idt180" in script or "tvResumen" in script: return "Descripción detallada del inmueble en litigio."
            return "Dato Dummy"
            
        mock_nodriver_page.evaluate.side_effect = evaluate_stub
        
        data = await scraper.extract_tab_remate()
        
        assert data["Expediente"] == "00123-2026-0-1801-JR-CI-01"
        assert data["Juez"] == "JUAN PEREZ"
        assert data["Descripción"] == "Descripción detallada del inmueble en litigio."

@pytest.mark.asyncio
async def test_download_resolucion_pdf_test_mode(mock_nodriver_page, valid_config_json):
    """Prueba 2: Intercepción del PDF de resolución simulando el Stream binario en memoria."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_config_json)):
        
        scraper = RemajuExtractorScraper(mock_nodriver_page)
        pdf_stream = await scraper.download_resolucion_pdf(test_mode=True)
        
        assert isinstance(pdf_stream, io.BytesIO)
        assert b"%PDF" in pdf_stream.getvalue()

@pytest.mark.asyncio
async def test_extract_tab_inmuebles(mock_nodriver_page, valid_config_json):
    """Prueba 3: Cambio de pestaña e iteración posicional evaluando scrollpanels dinámicos en Inmuebles."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_config_json)):
        
        scraper = RemajuExtractorScraper(mock_nodriver_page)
        
        def evaluate_stub(script, *args, **kwargs):
            if "Inmuebles" in script and "click()" in script: return True
            if "dlgEstado" in script: return False 
            if "j_idt200" in script: return "Av. Larco 123"
            if "j_idt203" in script: return "Hipotecas y embargos"
            return ""

        mock_nodriver_page.evaluate.side_effect = evaluate_stub
        
        # Mock de fila y celdas seguras
        mock_row = AsyncMock()
        tds = [
            create_mock_td("P21008706"),                # Índice 0: Partida Registral
            create_mock_td("CASA"),                     # Índice 1: Tipo Inmueble
            create_mock_td("Av. Larco 123"),            # Índice 2: Sincronizado con el aserto
            create_mock_td("Hipotecas y embargos")      # Índice 3: Sincronizado con el aserto
        ]
        
        mock_row.select_all.return_value = tds
        mock_nodriver_page.select_all.return_value = [mock_row]
        
        inmuebles = await scraper.extract_tab_inmuebles()
        
        assert len(inmuebles) == 1
        assert inmuebles[0]["partida"] == "P21008706"
        assert inmuebles[0]["tipo"] == "CASA"
        assert inmuebles[0]["direccion"] == "Av. Larco 123"
        assert inmuebles[0]["carga_gravamen"] == "Hipotecas y embargos"

@pytest.mark.asyncio
async def test_extract_tab_cronograma_critical_phase(mock_nodriver_page, valid_config_json):
    """Prueba 4: Filtrado estricto y aislamiento de las fechas de la fase 'Publicación e Inscripcion'."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_config_json)):
        
        scraper = RemajuExtractorScraper(mock_nodriver_page)
        
        def evaluate_stub(script, *args, **kwargs):
            if "Cronograma" in script and "click()" in script: return True
            if "dlgEstado" in script: return False
            return ""

        mock_nodriver_page.evaluate.side_effect = evaluate_stub
        
        # Fila 1 (Fase no coincidente)
        row_1 = AsyncMock()
        row_1.select_all.return_value = [
            create_mock_td("Validación de Inscripción"),
            create_mock_td("22/09/2026"),
            create_mock_td("24/09/2026")
        ]
        
        # Fila 2 (Match rígido de negocio)
        row_2 = AsyncMock()
        row_2.select_all.return_value = [
            create_mock_td("Publicación e Inscripcion"),
            create_mock_td("12/09/2026"),
            create_mock_td("21/09/2026")
        ]
        
        mock_nodriver_page.select_all.return_value = [row_1, row_2]
        
        cronograma = await scraper.extract_tab_cronograma()
        
        assert cronograma["fase"] == "Publicación e Inscripcion"
        assert cronograma["fecha_inicio"] == "12/09/2026"
        assert cronograma["fecha_fin"] == "21/09/2026"

@pytest.mark.asyncio
async def test_safe_return_to_search(mock_nodriver_page, valid_config_json):
    """Prueba 5: Botón de retorno y validación asíncrona de URL de la bandeja con concordancia exacta."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=valid_config_json)):
        
        scraper = RemajuExtractorScraper(mock_nodriver_page)
        
        config = json.loads(valid_config_json)
        # Construcción dinámica absoluta exacta para concordar con la lógica del scraper
        absolute_target_url = f"{config['url_base']}{config['url_search_path']}"

        def evaluate_stub(script, *args, **kwargs):
            if "Regresar" in script and "click()" in script: return True
            if "dlgEstado" in script: return False
            if "window.location.href" in script:
                return absolute_target_url
            return ""

        mock_nodriver_page.evaluate.side_effect = evaluate_stub
        
        result = await scraper.return_to_search()
        assert result is True
