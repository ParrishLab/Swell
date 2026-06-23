from __future__ import annotations

from swell.shared import model_copy


def test_model_copy_uses_model_terminology() -> None:
    assert model_copy.MENU_MANAGE_MODELS == "Manage Models..."
    assert "model" in model_copy.TITLE_MODEL_FILE_REQUIRED.lower()
    assert "project-recorded model" in model_copy.mismatch_body("Mismatch").lower()

