from sdapp.analysis.core.segmentation import _candidate_model_config_names


def test_base_plus_checkpoint_prefers_base_plus_configs_only() -> None:
    names = _candidate_model_config_names(
        model_path="/tmp/sam2.1_hiera_base_plus.pt",
        checkpoint_id="sam2.1_hiera_base_plus",
    )
    assert names == [
        "sam2.1_hiera_base_plus.yaml",
        "sam2.1_hiera_b+.yaml",
        "sam2_hiera_base_plus.yaml",
        "sam2_hiera_b+.yaml",
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
        "sam2_hiera_s.yaml",
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
