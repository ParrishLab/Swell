from __future__ import annotations

from typing import Any, Callable

import numpy as np


class MetricsSettingsResolver:
    METRIC_KEYS = ("frames_per_sec", "scale_px_per_mm", "scale_points", "scale_axis_lock", "scale_image_path", "roi_points", "roi_mask")
    ROI_KEYS = ("roi_points", "roi_mask")

    @staticmethod
    def normalize(settings: dict | None) -> dict[str, object]:
        if not isinstance(settings, dict):
            return {}
        out: dict[str, object] = {}
        if "frames_per_sec" in settings:
            try:
                fps = float(settings.get("frames_per_sec"))
                if fps > 0:
                    out["frames_per_sec"] = float(fps)
            except Exception:
                pass
        if "scale_px_per_mm" in settings:
            try:
                scale = float(settings.get("scale_px_per_mm"))
                if scale > 0:
                    out["scale_px_per_mm"] = float(scale)
            except Exception:
                pass
        scale_points = settings.get("scale_points")
        if isinstance(scale_points, list) and len(scale_points) >= 2:
            clean_scale_points: list[list[float]] = []
            for pt in list(scale_points)[:2]:
                if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                    continue
                try:
                    clean_scale_points.append([float(pt[0]), float(pt[1])])
                except Exception:
                    continue
            if len(clean_scale_points) == 2:
                out["scale_points"] = clean_scale_points
        if "scale_axis_lock" in settings:
            out["scale_axis_lock"] = bool(settings.get("scale_axis_lock"))
        scale_image_path = str(settings.get("scale_image_path", "") or "").strip()
        if scale_image_path:
            out["scale_image_path"] = scale_image_path
        points = settings.get("roi_points")
        if isinstance(points, list) and points:
            clean_points: list[list[float]] = []
            for pt in points:
                if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                    continue
                try:
                    clean_points.append([float(pt[0]), float(pt[1])])
                except Exception:
                    continue
            if clean_points:
                out["roi_points"] = clean_points
        if settings.get("roi_mask") is not None:
            try:
                arr = np.asarray(settings.get("roi_mask"), dtype=bool)
                if arr.ndim == 2:
                    out["roi_mask"] = arr.copy()
            except Exception:
                pass
        return out

    @staticmethod
    def has_value(payload: dict[str, Any], key: str) -> bool:
        if key not in payload:
            return False
        value = payload.get(key)
        if key in {"frames_per_sec", "scale_px_per_mm"}:
            try:
                return float(value) > 0
            except (TypeError, ValueError):
                return False
        if key == "scale_points":
            return isinstance(value, list) and len(value) >= 2
        if key == "scale_axis_lock":
            return isinstance(value, bool)
        if key == "scale_image_path":
            return isinstance(value, str) and bool(value.strip())
        if key == "roi_points":
            return isinstance(value, list) and len(value) > 0
        if key == "roi_mask":
            try:
                arr = np.asarray(value, dtype=bool)
                return arr.ndim == 2 and arr.size > 0
            except Exception:
                return False
        return value is not None

    @staticmethod
    def values_equal(key: str, lhs: Any, rhs: Any) -> bool:
        if key == "roi_mask":
            try:
                return np.array_equal(np.asarray(lhs, dtype=bool), np.asarray(rhs, dtype=bool))
            except Exception:
                return False
        return lhs == rhs

    @classmethod
    def merge(
        cls,
        existing: dict | None,
        incoming: dict | None,
        *,
        merge_missing_only: bool = False,
    ) -> tuple[dict[str, object], bool]:
        merged = cls.normalize(existing)
        normalized_incoming = cls.normalize(incoming)
        changed = False
        incoming_has_roi = any(key in normalized_incoming for key in cls.ROI_KEYS)
        if incoming_has_roi:
            if merge_missing_only and cls.has_valid_roi(merged):
                normalized_incoming = {key: value for key, value in normalized_incoming.items() if key not in cls.ROI_KEYS}
            elif not merge_missing_only:
                for key in cls.ROI_KEYS:
                    if key in merged:
                        merged.pop(key, None)
                        changed = True
        for key, value in normalized_incoming.items():
            if merge_missing_only and cls.has_value(merged, key):
                continue
            current = merged.get(key)
            if cls.values_equal(key, current, value):
                continue
            if key == "roi_mask":
                merged[key] = np.asarray(value, dtype=bool).copy()
            elif key == "scale_points":
                merged[key] = [[float(pt[0]), float(pt[1])] for pt in list(value)[:2]]
            elif key == "roi_points":
                merged[key] = [[float(pt[0]), float(pt[1])] for pt in list(value)]
            else:
                merged[key] = value
            changed = True
        return merged, changed

    @staticmethod
    def has_valid_scale(settings: dict) -> bool:
        try:
            return float(settings.get("scale_px_per_mm")) > 0
        except Exception:
            return False

    @staticmethod
    def has_valid_roi(settings: dict) -> bool:
        raw_mask = settings.get("roi_mask")
        if raw_mask is not None:
            try:
                arr = np.asarray(raw_mask, dtype=bool)
                if arr.ndim == 2 and arr.size > 0 and np.any(arr):
                    return True
            except Exception:
                pass
        points = settings.get("roi_points")
        return isinstance(points, list) and len(points) >= 3

    @classmethod
    def resolve_for_event(
        cls,
        *,
        event_id: str,
        analysis_sidecar: dict[str, dict] | None,
        project_metadata: dict | None,
    ) -> dict[str, object]:
        global_defaults: dict[str, object] = {}
        if isinstance(project_metadata, dict):
            raw_defaults = project_metadata.get("global_metrics_defaults")
            if isinstance(raw_defaults, dict):
                global_defaults = dict(raw_defaults)
        event_payload = dict((analysis_sidecar or {}).get(str(event_id), {}) or {})
        local_settings = dict(event_payload.get("metrics_settings", {}) or {})
        merged, _changed = cls.merge(global_defaults, local_settings, merge_missing_only=False)
        return merged

    @classmethod
    def prerequisites_for_events(
        cls,
        *,
        event_ids: list[str],
        metrics_loader: Callable[[str], dict | None],
    ) -> dict[str, dict[str, object]]:
        if not event_ids:
            return {
                "propagation_speed": {"enabled": False, "reason": "No events selected."},
                "area_recruited": {"enabled": False, "reason": "No events selected."},
                "relative_area_recruited": {"enabled": False, "reason": "No events selected."},
            }
        has_scale_flags: list[bool] = []
        has_roi_flags: list[bool] = []
        for event_id in [str(v) for v in event_ids]:
            metrics = cls.normalize(metrics_loader(str(event_id)) or {})
            has_scale_flags.append(bool(cls.has_valid_scale(metrics)))
            has_roi_flags.append(bool(cls.has_valid_roi(metrics)))

        all_scale = all(has_scale_flags)
        all_roi = all(has_roi_flags)
        any_scale = any(has_scale_flags)
        any_roi = any(has_roi_flags)

        def _reason_all_or_mixed(any_ready: bool, noun: str) -> str:
            if any_ready:
                return f"Some selected events are missing {noun}."
            return f"No selected events have {noun}."

        return {
            "propagation_speed": {
                "enabled": bool(all_scale),
                "reason": "" if all_scale else _reason_all_or_mixed(any_scale, "scale"),
            },
            "area_recruited": {
                "enabled": bool(all_scale and all_roi),
                "reason": (
                    ""
                    if all_scale and all_roi
                    else (
                        "Some selected events are missing scale and ROI."
                        if (any_scale and any_roi and not all_scale and not all_roi)
                        else (
                            _reason_all_or_mixed(any_scale, "scale")
                            if not all_scale
                            else _reason_all_or_mixed(any_roi, "ROI")
                        )
                    )
                ),
            },
            "relative_area_recruited": {
                "enabled": bool(all_roi),
                "reason": "" if all_roi else _reason_all_or_mixed(any_roi, "ROI"),
            },
        }
