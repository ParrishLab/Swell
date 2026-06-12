from __future__ import annotations

# Schema 3 adds optional embedded source images (additive, backward compatible:
# v2 files load unchanged and v3 files without embedded images are equivalent to v2).
HOST_PROJECT_SCHEMA_VERSION = 3
HOST_PERSISTENCE_OWNER = "host_sdproj"

MANIFEST_FILENAME = "manifest.json"
STACK_FILENAME = "stack.json"
EVENTS_FILENAME = "events.json"
ANALYSIS_SIDECAR_FILENAME = "analysis_sidecar.json"
EMBEDDED_IMAGES_FILENAME = "images_embedded.json"
EMBEDDED_IMAGES_DIR = "images"
EMBEDDED_IMAGES_INDEX_KEY = "embedded"

METADATA_GLOBAL_METRICS_DEFAULTS_KEY = "global_metrics_defaults"
METADATA_DC_TRACE_ATTACHMENT_KEY = "dc_trace_attachment"
METADATA_EMBED_IMAGES_KEY = "embed_source_images"
METRICS_SETTINGS_KEY = "metrics_settings"

PERSISTENCE_OWNER_FIELD = "owner"
PERSISTENCE_BLOCK_FIELD = "persistence"
SCHEMA_VERSION_FIELD = "schema_version"
ACTIVE_EVENT_ID_FIELD = "active_event_id"
METADATA_FIELD = "metadata"
