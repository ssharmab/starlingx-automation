# SPDX-License-Identifier: Apache-2.0
"""Tests for tools/rvmc/rvmc_errors.py — full branch coverage."""
import pytest
from tools.rvmc.rvmc_errors import (
    RvmcError,
    RvmcAuthError,
    RvmcBootError,
    RvmcConfigError,
    RvmcConnectionError,
    RvmcMediaError,
    RvmcPowerError,
)


class TestRvmcError:
    def test_default_code(self):
        e = RvmcError("boom")
        assert e.message == "boom"
        assert e.code == 1
        assert str(e) == "boom"

    def test_custom_code(self):
        e = RvmcError("bad", code=42)
        assert e.code == 42

    def test_is_exception(self):
        with pytest.raises(RvmcError):
            raise RvmcError("x")


class TestSubclasses:
    @pytest.mark.parametrize("cls", [
        RvmcAuthError,
        RvmcBootError,
        RvmcConfigError,
        RvmcConnectionError,
        RvmcMediaError,
        RvmcPowerError,
    ])
    def test_is_rvmc_error(self, cls):
        e = cls("msg")
        assert isinstance(e, RvmcError)
        assert e.message == "msg"
        assert e.code == 1

    def test_catch_base_catches_subclass(self):
        with pytest.raises(RvmcError):
            raise RvmcConnectionError("unreachable")
