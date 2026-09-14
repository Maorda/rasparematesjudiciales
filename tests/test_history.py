# tests/test_history.py
import pytest
import json
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock, PropertyMock
from src.core.storage.history_manager import RemajuHistoryManager

# --- CASOS DE PRUEBA ---

def test_history_manager_initialization_creates_file_if_not_exists():
    """Prueba que el manager inicialice correctamente un historial con una lista vacía si el archivo no existe."""
    with patch("pathlib.Path.exists", return_value=False), \
         patch("builtins.open", mock_open()) as mocked_file:
        
        RemajuHistoryManager(filepath="dummy_history.json")
        
        # Valida de forma robusta que se haya escrito la estructura de lista vacía en el archivo,
        # tolerando variaciones de formato o indentación generadas por json.dump.
        handle = mocked_file()
        written_data = "".join(call.args[0] for call in handle.write.mock_calls if call.args)
        assert "[]" in written_data

def test_is_processed_identifies_duplicates_accurately():
    """Prueba que se identifiquen duplicados basándose estrictamente en la combinación expediente + convocatoria."""
    # Simulación de un historial previo con un registro real
    mock_history_data = json.dumps([
        {
            "expediente": "00512-2023-0-1408-JR-CI-01",
            "convocatoria": "PRIMERA CONVOCATORIA"
        }
    ])
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_history_data)):
        
        manager = RemajuHistoryManager(filepath="dummy_history.json")
        
        # Mismo expediente, misma convocatoria -> Debe retornar True (Omitir/Duplicado)
        assert manager.is_processed("00512-2023-0-1408-JR-CI-01", "PRIMERA CONVOCATORIA") is True
        
        # Mismo expediente, NUEVA convocatoria -> Debe retornar False (Apto para procesar)
        assert manager.is_processed("00512-2023-0-1408-JR-CI-01", "SEGUNDA CONVOCATORIA") is False
        
        # Expediente totalmente nuevo -> Debe retornar False (Apto para procesar)
        assert manager.is_processed("00999-2026-0-1801-JR-CI-01", "PRIMERA CONVOCATORIA") is False

def test_save_processed_appends_new_record_atomically():
    """Prueba que un nuevo expediente se añada correctamente a la lista y se invoque el guardado atómico."""
    mock_history_data = json.dumps([]) # Historial inicialmente vacío
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_history_data)), \
         patch.object(RemajuHistoryManager, "_save_data_atomically") as mock_save_atomic:
        
        manager = RemajuHistoryManager(filepath="dummy_history.json")
        
        # Guardar un registro nuevo
        manager.save_processed("00512-2023-0-1408-JR-CI-01", "PRIMERA CONVOCATORIA")
        
        # Verifica que el registro haya sido incorporado y se haya ordenado el guardado atómico con éxito
        mock_save_atomic.assert_called_once()
        saved_list = mock_save_atomic.call_args[0][0]
        assert len(saved_list) == 1
        assert saved_list[0]["expediente"] == "00512-2023-0-1408-JR-CI-01"
