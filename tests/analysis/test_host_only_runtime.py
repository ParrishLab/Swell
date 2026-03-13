from __future__ import annotations

import pytest

from sdapp.analysis.app import SDSegmentationApp, main as analysis_main


def test_constructor_rejects_standalone_mode():
    with pytest.raises(RuntimeError, match="Standalone SD Segmenter runtime has been removed"):
        SDSegmentationApp(object(), host_mode=False)


def test_analysis_main_rejects_standalone_launch():
    with pytest.raises(RuntimeError, match="Standalone SD Segmenter launch is not supported"):
        analysis_main()
