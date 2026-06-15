# SPDX-License-Identifier: Apache-2.0
"""Tests for utils/tool_result.py — full branch coverage."""
import pytest
from utils.tool_result import ResultStatus, ToolResult


class TestResultStatus:
    def test_all_values(self):
        assert ResultStatus.SUCCESS      == "success"
        assert ResultStatus.FAILURE      == "failure"
        assert ResultStatus.UNAVAILABLE  == "unavailable"
        assert ResultStatus.TIMEOUT      == "timeout"
        assert ResultStatus.AUTH_ERROR   == "auth_error"
        assert ResultStatus.NOT_CONNECTED == "not_connected"

    def test_is_str(self):
        assert isinstance(ResultStatus.SUCCESS, str)


class TestToolResult:
    def test_success_property_true(self):
        r = ToolResult(status=ResultStatus.SUCCESS, exit_code=0)
        assert r.success is True

    def test_success_property_false(self):
        r = ToolResult(status=ResultStatus.FAILURE, exit_code=1)
        assert r.success is False

    def test_defaults(self):
        r = ToolResult(status=ResultStatus.SUCCESS, exit_code=0)
        assert r.stdout == ""
        assert r.stderr == ""
        assert r.duration_seconds == 0.0
        assert r.command == ""
        assert r.data == {}
        assert r.correlation_id != ""

    def test_to_dict_keys(self):
        r = ToolResult(status=ResultStatus.SUCCESS, exit_code=0,
                       stdout="out", stderr="err", duration_seconds=1.5,
                       command="kubectl get pods", correlation_id="abc-123",
                       data={"x": 1})
        d = r.to_dict()
        assert d["status"]           == "success"
        assert d["success"]          is True
        assert d["exit_code"]        == 0
        assert d["stdout"]           == "out"
        assert d["stderr"]           == "err"
        assert d["duration_seconds"] == 1.5
        assert d["command"]          == "kubectl get pods"
        assert d["correlation_id"]   == "abc-123"
        assert d["data"]             == {"x": 1}

    def test_to_dict_rounds_duration(self):
        r = ToolResult(status=ResultStatus.SUCCESS, exit_code=0,
                       duration_seconds=1.23456789)
        assert r.to_dict()["duration_seconds"] == 1.235

    def test_error_factory_with_correlation_id(self):
        r = ToolResult.error(ResultStatus.FAILURE, "bad thing",
                             command="cmd", correlation_id="cid-1")
        assert r.status           == ResultStatus.FAILURE
        assert r.exit_code        == -1
        assert r.stderr           == "bad thing"
        assert r.command          == "cmd"
        assert r.correlation_id   == "cid-1"

    def test_error_factory_generates_correlation_id(self):
        r = ToolResult.error(ResultStatus.TIMEOUT, "timed out")
        assert r.correlation_id != ""
        assert len(r.correlation_id) > 0

    def test_error_factory_all_statuses(self):
        for status in ResultStatus:
            r = ToolResult.error(status, "msg")
            assert r.status == status
            assert r.exit_code == -1
