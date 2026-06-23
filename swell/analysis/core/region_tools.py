REGION_INCLUDE_TOOL = "region_include"
REGION_EXCLUDE_TOOL = "region_exclude"
REGION_LEGACY_TOOL = "region"


def is_region_tool_mode(mode) -> bool:
    return str(mode) in {REGION_INCLUDE_TOOL, REGION_EXCLUDE_TOOL, REGION_LEGACY_TOOL}


def region_mode_from_tool_mode(mode) -> str | None:
    mode = str(mode)
    if mode in {REGION_INCLUDE_TOOL, REGION_LEGACY_TOOL}:
        return "include"
    if mode == REGION_EXCLUDE_TOOL:
        return "exclude"
    return None


def region_tool_mode_for_region_mode(mode) -> str:
    return REGION_EXCLUDE_TOOL if str(mode) == "exclude" else REGION_INCLUDE_TOOL
