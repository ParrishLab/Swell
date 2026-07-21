from swell.analysis.core.runtime_state import HostModeState


def test_host_mode_state_defaults_to_standalone_analysis() -> None:
    assert HostModeState().host_mode is False


def test_host_mode_state_preserves_explicit_host_launch() -> None:
    assert HostModeState(host_mode=True).host_mode is True
