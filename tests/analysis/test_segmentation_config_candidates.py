from sdapp.analysis.core import segmentation as segmentation_mod
from sdapp.analysis.core.segmentation import _candidate_model_config_names


def test_base_plus_checkpoint_prefers_base_plus_configs_only() -> None:
    names = _candidate_model_config_names(
        model_path="/tmp/sam2.1_hiera_base_plus.pt",
        checkpoint_id="sam2.1_hiera_base_plus",
    )
    assert names == [
        "sam2.1_hiera_base_plus.yaml",
        "sam2.1_hiera_b+.yaml",
    ]
    assert all("_hiera_s.yaml" not in name for name in names)
    assert all("_hiera_t.yaml" not in name for name in names)
    assert all("_hiera_l.yaml" not in name for name in names)


def test_small_variant_prefers_small_only() -> None:
    names = _candidate_model_config_names(
        model_path="/tmp/sam2.1_hiera_s.pt",
        checkpoint_id="sam2.1_hiera_s",
    )
    assert names == [
        "sam2.1_hiera_s.yaml",
    ]


def test_unknown_variant_uses_bounded_probe_order() -> None:
    names = _candidate_model_config_names(
        model_path="/tmp/custom_model.pt",
        checkpoint_id=None,
    )
    assert names[:5] == [
        "sam2.1_hiera_base_plus.yaml",
        "sam2.1_hiera_b+.yaml",
        "sam2.1_hiera_s.yaml",
        "sam2.1_hiera_t.yaml",
        "sam2.1_hiera_l.yaml",
    ]


def test_ensure_runtime_stdio_replaces_none_streams(monkeypatch) -> None:
    monkeypatch.setattr(segmentation_mod.sys, "stdout", None, raising=False)
    monkeypatch.setattr(segmentation_mod.sys, "stderr", None, raising=False)

    segmentation_mod._ensure_runtime_stdio()

    assert segmentation_mod.sys.stdout is not None
    assert segmentation_mod.sys.stderr is not None
    assert hasattr(segmentation_mod.sys.stdout, "write")
    assert hasattr(segmentation_mod.sys.stderr, "write")
