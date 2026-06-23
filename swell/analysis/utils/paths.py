# Compatibility shim — path utilities now live in swell.shared.utils.paths.
from swell.shared.utils.paths import (  # noqa: F401
    ensure_dir,
    get_app_root,
    get_bundle_root,
    get_package_root,
    get_resources_root,
    get_runtime_root,
    resolve_existing_directory,
    resolve_path,
)
