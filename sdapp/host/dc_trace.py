from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from sdapp.shared.trace import TraceAdapter, TraceRecord


def _load_h5py():
    try:
        import h5py  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised via public methods
        raise RuntimeError("DC trace import requires the 'h5py' package.") from exc
    return h5py


def _decode_scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return _decode_scalar(value.item())
        return [_decode_scalar(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_decode_scalar(item) for item in value]
    return value


def _flatten_string_values(value: Any) -> list[str]:
    decoded = _decode_scalar(value)
    if decoded is None:
        return []
    if isinstance(decoded, str):
        return [decoded]
    if isinstance(decoded, (list, tuple)):
        out: list[str] = []
        for item in decoded:
            out.extend(_flatten_string_values(item))
        return [str(item) for item in out if str(item)]
    return [str(decoded)]


def _as_float_list(value: Any) -> list[float]:
    if value is None:
        return []
    arr = np.asarray(value)
    if arr.ndim == 0:
        try:
            return [float(arr.item())]
        except (TypeError, ValueError):
            return []
    out: list[float] = []
    for item in arr.reshape(-1).tolist():
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def _path_exists(handle: Any, path: str) -> bool:
    try:
        handle[path]
        return True
    except Exception:
        return False


def _read_node(handle: Any, path: str) -> Any:
    try:
        node = handle[path]
    except Exception:
        return None
    try:
        return node[()]
    except Exception:
        return node


def _get_node(handle: Any, path: str) -> Any:
    try:
        return handle[path]
    except Exception:
        return None


def _read_first(handle: Any, paths: list[str]) -> Any:
    for path in paths:
        value = _read_node(handle, path)
        if value is not None:
            return value
    return None


def _active_channel_mask(handle: Any) -> list[bool] | None:
    raw = _read_first(
        handle,
        [
            "header/Acquisition/IsAnalogChannelActive",
            "header/IsAIChannelActive",
            "header/Acquisition/IsAIChannelActive",
            "header/IsAIChannelActive",
        ],
    )
    if raw is None:
        return None
    arr = np.asarray(raw).reshape(-1)
    if arr.size == 0:
        return None
    return [bool(item) for item in arr.tolist()]


def _normalize_channel_values(values: list[Any], n_channels: int, default_prefix: str) -> list[str]:
    if not default_prefix:
        fallback = ["" for _ in range(n_channels)]
    else:
        fallback = [f"{default_prefix} {idx + 1}" for idx in range(n_channels)]
    if not values:
        return fallback
    normalized = [str(item) for item in values[:n_channels]]
    if len(normalized) < n_channels:
        normalized.extend(fallback[len(normalized):n_channels])
    return normalized


def _apply_active_mask(values: list[str], active_mask: list[bool] | None, n_channels: int, default_prefix: str) -> list[str]:
    normalized = _normalize_channel_values(values, len(active_mask) if active_mask else n_channels, default_prefix)
    if active_mask:
        filtered = [value for value, is_active in zip(normalized, active_mask) if bool(is_active)]
        if filtered:
            return _normalize_channel_values(filtered, n_channels, default_prefix)
    return _normalize_channel_values(normalized, n_channels, default_prefix)


def _coerce_segments(handle: Any) -> list[tuple[int, int]]:
    return []


def _sorted_sweep_names(handle: Any) -> list[str]:
    try:
        keys = list(handle.keys())
    except Exception:
        return []
    sweeps = [str(key) for key in keys if str(key).startswith("sweep_")]
    sweeps.sort()
    return sweeps


def _evaluate_wavesurfer_scaling(
    raw_counts: np.ndarray,
    coefficients: np.ndarray | None,
    channel_scale: float | None,
) -> np.ndarray:
    x = np.asarray(raw_counts, dtype=np.float64)
    if coefficients is None:
        scaled = x
    else:
        coeffs = np.asarray(coefficients, dtype=np.float64).reshape(-1)
        if coeffs.size == 0:
            scaled = x
        else:
            # Match ws.scaledDoubleAnalogDataFromRaw(): coefficients are ordered
            # from low to high power and evaluated with Horner's method.
            scaled = np.full_like(x, coeffs[-1], dtype=np.float64)
            for coeff in coeffs[-2::-1]:
                scaled = coeff + x * scaled
    if channel_scale is None:
        return scaled
    scale = float(channel_scale)
    if abs(scale) <= 1e-12:
        return scaled
    return scaled / scale


def _coefficients_by_channel(
    value: Any,
    *,
    data_channel_count: int,
    configured_channel_count: int,
) -> list[np.ndarray]:
    if value is None:
        return []
    arr = np.asarray(value, dtype=np.float64)
    if arr.ndim == 0:
        return [arr.reshape(1)]
    if arr.ndim == 1:
        return [arr.reshape(-1)]
    if arr.ndim > 2:
        arr = arr.reshape(arr.shape[0], -1)
    rows, cols = int(arr.shape[0]), int(arr.shape[1])
    matrix = arr
    resolved_orientation = False
    if data_channel_count > 0:
        if rows == data_channel_count and cols != data_channel_count:
            matrix = arr
            resolved_orientation = True
        elif cols == data_channel_count and rows != data_channel_count:
            matrix = arr.transpose()
            resolved_orientation = True
    if not resolved_orientation and configured_channel_count > 0:
        if rows == configured_channel_count and cols != configured_channel_count:
            matrix = arr
        elif cols == configured_channel_count and rows != configured_channel_count:
            matrix = arr.transpose()
        elif rows != configured_channel_count and cols != configured_channel_count:
            if cols >= configured_channel_count and rows < configured_channel_count:
                matrix = arr.transpose()
    return [np.asarray(matrix[idx, :], dtype=np.float64).reshape(-1) for idx in range(int(matrix.shape[0]))]


def _filtered_scaling_coefficients(
    value: Any,
    *,
    active_mask: list[bool] | None,
    configured_channel_count: int,
    n_channels: int,
) -> list[np.ndarray]:
    rows = _coefficients_by_channel(
        value,
        data_channel_count=n_channels,
        configured_channel_count=configured_channel_count,
    )
    if active_mask and len(rows) >= len(active_mask):
        filtered = [row for row, is_active in zip(rows, active_mask) if bool(is_active)]
        if filtered:
            rows = filtered
    if len(rows) < n_channels:
        rows.extend([np.array([], dtype=np.float64) for _ in range(n_channels - len(rows))])
    return rows[:n_channels]


def _infer_trace_layout(
    shape: tuple[int, ...],
    *,
    candidate_channel_count: int,
) -> tuple[int, int, bool]:
    if len(shape) != 2:
        return 0, 0, False
    dim0 = int(shape[0])
    dim1 = int(shape[1])
    if candidate_channel_count > 0:
        if dim0 == candidate_channel_count and dim1 != candidate_channel_count:
            return dim0, dim1, True
        if dim1 == candidate_channel_count and dim0 != candidate_channel_count:
            return dim1, dim0, False
    if dim0 <= 32 and dim1 > dim0:
        return dim0, dim1, True
    if dim1 <= 32 and dim0 > dim1:
        return dim1, dim0, False
    return dim1, dim0, False


class WaveSurferH5Adapter(TraceAdapter):
    source_type = "wavesurfer_h5"

    def sniff(self, path: Path) -> bool:
        candidate = Path(path)
        if candidate.suffix.lower() not in {".h5", ".hdf5"}:
            return False
        h5py = _load_h5py()
        try:
            with h5py.File(str(candidate), "r") as handle:
                return bool(_sorted_sweep_names(handle)) and _path_exists(handle, "header")
        except Exception:
            return False

    def load_metadata(self, path: Path) -> dict[str, Any]:
        h5py = _load_h5py()
        source_path = Path(path).expanduser().resolve()
        with h5py.File(str(source_path), "r") as handle:
            sweep_names = _sorted_sweep_names(handle)
            if not sweep_names:
                raise ValueError("Unsupported WaveSurfer file: missing sweep_*/analogScans data.")
            first_analog = _get_node(handle, f"{sweep_names[0]}/analogScans")
            shape = tuple(getattr(first_analog, "shape", ()) or ())
            if len(shape) != 2 or min(int(shape[0]), int(shape[1])) <= 0:
                raise ValueError("Unsupported WaveSurfer file: analogScans dataset is missing or invalid.")
            sample_rate = self._sample_rate_hz(handle)
            active_mask = _active_channel_mask(handle)
            active_channel_count = sum(1 for flag in list(active_mask or []) if bool(flag))
            raw_channel_names = _flatten_string_values(
                _read_first(
                    handle,
                    [
                        "header/Acquisition/AnalogChannelNames",
                        "header/Acquisition/AIChannelNames",
                        "header/AnalogChannelNames",
                        "header/AIChannelNames",
                    ],
                )
            )
            raw_units = _flatten_string_values(
                _read_first(
                    handle,
                    [
                        "header/Acquisition/AnalogChannelUnits",
                        "header/Acquisition/AIChannelUnits",
                        "header/AnalogChannelUnits",
                        "header/AIChannelUnits",
                    ],
                )
            )
            raw_scales = _as_float_list(
                _read_first(
                    handle,
                    [
                        "header/Acquisition/AnalogChannelScales",
                        "header/Acquisition/AIChannelScales",
                        "header/AnalogChannelScales",
                        "header/AIChannelScales",
                    ],
                )
            )
            candidate_channel_count = (
                int(active_channel_count)
                if int(active_channel_count) > 0
                else max(
                    len(raw_channel_names),
                    len(raw_units),
                    len(raw_scales),
                )
            )
            n_channels, _sample_count, channels_first = _infer_trace_layout(
                shape,
                candidate_channel_count=int(candidate_channel_count),
            )
            if n_channels <= 0:
                raise ValueError("Unsupported WaveSurfer file: unable to infer analogScans orientation.")
            channel_names = _apply_active_mask(
                raw_channel_names,
                active_mask,
                n_channels,
                "Channel",
            )
            units = _apply_active_mask(
                raw_units,
                active_mask,
                n_channels,
                "",
            )
            scales = self._channel_scales(handle, n_channels=n_channels, active_mask=active_mask)
            scaling_coefficients = _filtered_scaling_coefficients(
                _read_first(
                    handle,
                    [
                        "header/Acquisition/AnalogScalingCoefficients",
                        "header/AIScalingCoefficients",
                    ],
                ),
                active_mask=active_mask,
                configured_channel_count=max(
                    len(active_mask or []),
                    len(raw_channel_names),
                    len(raw_units),
                    len(raw_scales),
                ),
                n_channels=n_channels,
            )
            offset = 0
            segments: list[tuple[int, int]] = []
            for sweep_name in sweep_names:
                analog = _get_node(handle, f"{sweep_name}/analogScans")
                analog_shape = tuple(getattr(analog, "shape", ()) or ())
                if len(analog_shape) != 2:
                    continue
                _n_channels, sample_count, _channels_first = _infer_trace_layout(
                    analog_shape,
                    candidate_channel_count=int(candidate_channel_count or n_channels),
                )
                if sample_count <= 0:
                    continue
                segments.append((offset, offset + int(sample_count)))
                offset += int(sample_count)
            total_samples = int(segments[-1][1]) if segments else 0
            duration_s = None
            if sample_rate and sample_rate > 0 and total_samples > 0:
                duration_s = float(total_samples) / float(sample_rate)
            return {
                "source_type": self.source_type,
                "source_path": str(source_path),
                "sample_rate_hz": sample_rate,
                "channel_names": channel_names,
                "units": units,
                "channel_scales": scales,
                "scaling_coefficients": scaling_coefficients,
                "sweep_names": sweep_names,
                "sweep_count": len(sweep_names),
                "segments": [list(segment) for segment in segments],
                "total_samples": total_samples,
                "duration_s": duration_s,
                "channels_first": bool(channels_first),
            }

    def load_trace(self, path: Path, channel_selection: int | None = None) -> TraceRecord:
        metadata = self.load_metadata(path)
        channel_names = list(metadata.get("channel_names") or [])
        units = list(metadata.get("units") or [])
        channel_index = 0 if channel_selection is None else int(channel_selection)
        if channel_index < 0 or channel_index >= len(channel_names):
            raise IndexError(f"Channel index out of range: {channel_index}")

        h5py = _load_h5py()
        source_path = Path(path).expanduser().resolve()
        selected_chunks: list[np.ndarray] = []
        segments: list[tuple[int, int]] = []
        offset = 0
        with h5py.File(str(source_path), "r") as handle:
            sweep_names = list(metadata.get("sweep_names") or [])
            scales = _as_float_list(metadata.get("channel_scales"))
            raw_coefficients = list(metadata.get("scaling_coefficients") or [])
            for sweep_name in sweep_names:
                raw_dataset = _read_node(handle, f"{sweep_name}/analogScans")
                raw = np.asarray(raw_dataset)
                if raw.ndim != 2 or raw.shape[0] <= 0:
                    continue
                candidate_channel_count = max(len(channel_names), len(units), len(scales))
                n_channels, _sample_count, channels_first = _infer_trace_layout(
                    tuple(raw.shape),
                    candidate_channel_count=int(candidate_channel_count),
                )
                if channel_index >= n_channels:
                    raise ValueError(
                        f"Channel index {channel_index} exceeds analog channel count {n_channels} in {sweep_name}."
                    )
                selected = raw[channel_index, :] if channels_first else raw[:, channel_index]
                if np.issubdtype(selected.dtype, np.integer):
                    coeff_row = None
                    if channel_index < len(raw_coefficients):
                        coeff_row = np.asarray(raw_coefficients[channel_index], dtype=np.float64)
                    scale = float(scales[channel_index]) if channel_index < len(scales) else None
                    values = _evaluate_wavesurfer_scaling(selected, coeff_row, scale)
                else:
                    values = np.asarray(selected, dtype=np.float64)
                selected_chunks.append(np.asarray(values, dtype=np.float64))
                sample_count = int(values.shape[0])
                segments.append((offset, offset + sample_count))
                offset += sample_count
        if not selected_chunks:
            raise ValueError("No analog trace samples were found in the selected WaveSurfer file.")
        concatenated = np.concatenate(selected_chunks, axis=0)
        return TraceRecord(
            source_type=self.source_type,
            channel_names=[channel_names[channel_index]],
            units=[units[channel_index] if channel_index < len(units) else ""],
            sample_rate_hz=(
                None if metadata.get("sample_rate_hz") is None else float(metadata.get("sample_rate_hz"))
            ),
            timestamps_s=None,
            signals=np.asarray(concatenated, dtype=np.float64).reshape(-1, 1),
            segments=segments,
            start_time_s=0.0,
            metadata={
                "source_path": str(source_path),
                "channel_index": int(channel_index),
                "channel_name": channel_names[channel_index],
                "unit": units[channel_index] if channel_index < len(units) else "",
                "sweep_count": int(metadata.get("sweep_count", 0) or 0),
            },
        )

    @staticmethod
    def _sample_rate_hz(handle: Any) -> float | None:
        raw = _read_first(
            handle,
            [
                "header/AcquisitionSampleRate",
                "header/Acquisition/AcquisitionSampleRate",
                "header/Acquisition/SampleRate",
            ],
        )
        floats = _as_float_list(raw)
        if not floats:
            return None
        value = float(floats[0])
        return value if value > 0 else None

    @staticmethod
    def _channel_scales(handle: Any, *, n_channels: int, active_mask: list[bool] | None) -> list[float]:
        scales = _as_float_list(
            _read_first(
                handle,
                [
                    "header/Acquisition/AnalogChannelScales",
                    "header/Acquisition/AIChannelScales",
                    "header/AnalogChannelScales",
                    "header/AIChannelScales",
                ],
            )
        )
        if active_mask and len(scales) >= len(active_mask):
            filtered = [scale for scale, is_active in zip(scales, active_mask) if bool(is_active)]
            if filtered:
                scales = filtered
        if len(scales) < n_channels:
            scales.extend([1.0] * (n_channels - len(scales)))
        return [float(scale) for scale in scales[:n_channels]]
