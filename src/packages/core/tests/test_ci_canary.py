"""Temporary: proves the pytest workflow fails on a red test. Removed before merge."""


def test_ci_gate_goes_red():
    assert False, "deliberately failing — this file is removed before merge"
