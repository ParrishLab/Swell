from __future__ import annotations


MENU_MANAGE_MODELS = "Manage Models..."
TITLE_MANAGE_MODELS = "Manage Models"
TITLE_MODEL_FILE_MISSING = "Model File Missing"
TITLE_MODEL_DOWNLOAD_FAILED = "Model Download Failed"
TITLE_MODEL_DOWNLOADED = "Model Downloaded"
TITLE_MODEL_FILE_REQUIRED = "Model File Required"
TITLE_MODEL_METADATA_MISMATCH = "Model Metadata Mismatch"

STATUS_MODEL_FILE_MISSING = "Model File Missing"
STATUS_MODEL_DISABLED = "Model Disabled"
STATUS_MODEL_ERROR = "Model Error"
STATUS_MODEL_READY = "Model Ready"


def onboarding_body() -> str:
    return (
        "No local SAM2 model file is available.\n\n"
        "Yes = Download approved default model file\n"
        "No = Select a local model file\n"
        "Cancel = Keep model-based tools disabled"
    )


def mismatch_body(detail: str) -> str:
    return (
        f"{detail}\n\n"
        "Yes = Switch to project-recorded model file\n"
        "No = Continue with current active model\n"
        "Cancel = Disable model-based tools (review-only)"
    )
