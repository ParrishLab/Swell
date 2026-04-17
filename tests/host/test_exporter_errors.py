import pytest
from unittest.mock import patch, mock_open
import numpy as np
from pathlib import Path

from sdapp.host.exporter import _write_metric_csv, _metric_table_rows

def test_exporter_nan_handling():
    # _metric_table_rows should convert NaN to empty string
    frame_indices = [0, 1]
    time_sec = [0.0, 1.0]
    values = np.array([1.5, np.nan])
    
    rows = _metric_table_rows(frame_indices, time_sec, values, "my_metric")
    
    assert rows["columns"] == ["frame_index", "frame_display", "time_sec", "my_metric"]
    assert rows["rows"][0] == [0, 1, 0.0, 1.5]
    assert rows["rows"][1] == [1, 2, 1.0, ""] # NaN becomes empty string

def test_exporter_io_error_propagates():
    # If the disk is full or path is read-only, it should raise IOError, not be swallowed.
    frame_indices = [0]
    time_sec = [0.0]
    values = np.array([1.5])
    
    with patch.object(Path, 'open', side_effect=IOError("Disk Full")):
        with pytest.raises(IOError, match="Disk Full"):
            _write_metric_csv(Path("/fake/path.csv"), frame_indices, time_sec, values, "my_metric")
