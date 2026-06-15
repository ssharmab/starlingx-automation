# SPDX-License-Identifier: Apache-2.0
"""Tests for tools/kubernetes/get_logs.py — full branch coverage."""
import pytest
from unittest.mock import MagicMock

from utils.tool_result import ToolResult, ResultStatus
from utils.ssh_connection import SSHConnection


def _tool():
    from tools.kubernetes.get_logs import GetLogsTool
    conn = MagicMock(spec=SSHConnection)
    conn.__class__ = SSHConnection
    conn.execute.return_value = ToolResult(
        status=ResultStatus.SUCCESS, exit_code=0, stdout="log line", stderr="")
    return GetLogsTool(conn, namespace="default"), conn


class TestValidateName:
    def test_valid_name(self):
        from tools.kubernetes.get_logs import _validate_name
        assert _validate_name("my-pod-1", "pod") == "my-pod-1"

    def test_single_char_valid(self):
        from tools.kubernetes.get_logs import _validate_name
        assert _validate_name("a", "pod") == "a"

    def test_invalid_uppercase(self):
        from tools.kubernetes.get_logs import _validate_name
        assert _validate_name("MyPod", "pod") is None

    def test_invalid_special_chars(self):
        from tools.kubernetes.get_logs import _validate_name
        assert _validate_name("pod name!", "pod") is None


class TestValidateSince:
    def test_valid_seconds(self):
        from tools.kubernetes.get_logs import _validate_since
        assert _validate_since("30s") == "30s"

    def test_valid_minutes(self):
        from tools.kubernetes.get_logs import _validate_since
        assert _validate_since("5m") == "5m"

    def test_valid_hours(self):
        from tools.kubernetes.get_logs import _validate_since
        assert _validate_since("2h") == "2h"

    def test_invalid_days(self):
        from tools.kubernetes.get_logs import _validate_since
        assert _validate_since("1d") is None

    def test_invalid_no_unit(self):
        from tools.kubernetes.get_logs import _validate_since
        assert _validate_since("60") is None


class TestGetPodLogs:
    def test_invalid_pod_name_returns_failure(self):
        tool, _ = _tool()
        result = tool.get_pod_logs("INVALID!")
        assert result.status == ResultStatus.FAILURE
        assert result.exit_code == -1

    def test_valid_pod_no_container(self):
        tool, conn = _tool()
        result = tool.get_pod_logs("my-pod", tail_lines=20)
        assert result.success is True
        cmd = conn.execute.call_args[0][0]
        assert "my-pod" in cmd
        assert "--tail=20" in cmd

    def test_tail_clamped_to_max(self):
        tool, conn = _tool()
        tool.get_pod_logs("my-pod", tail_lines=999999)
        cmd = conn.execute.call_args[0][0]
        assert "--tail=5000" in cmd

    def test_tail_clamped_to_min(self):
        tool, conn = _tool()
        tool.get_pod_logs("my-pod", tail_lines=0)
        cmd = conn.execute.call_args[0][0]
        assert "--tail=1" in cmd

    def test_valid_container(self):
        tool, conn = _tool()
        tool.get_pod_logs("my-pod", container="main")
        cmd = conn.execute.call_args[0][0]
        assert "-c main" in cmd

    def test_invalid_container_returns_failure(self):
        tool, _ = _tool()
        result = tool.get_pod_logs("my-pod", container="INVALID!")
        assert result.status == ResultStatus.FAILURE


class TestGetPreviousLogs:
    def test_invalid_pod_name(self):
        tool, _ = _tool()
        result = tool.get_previous_logs("Bad Pod!")
        assert result.status == ResultStatus.FAILURE

    def test_valid(self):
        tool, conn = _tool()
        result = tool.get_previous_logs("my-pod", tail_lines=10)
        assert result.success is True
        cmd = conn.execute.call_args[0][0]
        assert "--previous" in cmd
        assert "--tail=10" in cmd

    def test_invalid_container(self):
        tool, _ = _tool()
        result = tool.get_previous_logs("my-pod", container="BAD!")
        assert result.status == ResultStatus.FAILURE

    def test_valid_container(self):
        tool, conn = _tool()
        result = tool.get_previous_logs("my-pod", container="sidecar")
        assert result.success is True
        cmd = conn.execute.call_args[0][0]
        assert "-c sidecar" in cmd


class TestGetLogsSince:
    def test_invalid_pod(self):
        tool, _ = _tool()
        result = tool.get_logs_since("Bad!", since="5m")
        assert result.status == ResultStatus.FAILURE

    def test_invalid_since(self):
        tool, _ = _tool()
        result = tool.get_logs_since("my-pod", since="1day")
        assert result.status == ResultStatus.FAILURE

    def test_valid(self):
        tool, conn = _tool()
        result = tool.get_logs_since("my-pod", since="30s")
        assert result.success is True
        cmd = conn.execute.call_args[0][0]
        assert "--since=30s" in cmd

    def test_valid_with_container(self):
        tool, conn = _tool()
        result = tool.get_logs_since("my-pod", since="5m", container="app")
        assert result.success is True
        cmd = conn.execute.call_args[0][0]
        assert "-c app" in cmd

    def test_invalid_container(self):
        tool, _ = _tool()
        result = tool.get_logs_since("my-pod", since="5m", container="BAD!")
        assert result.status == ResultStatus.FAILURE


class TestGetLogsTail:
    def test_invalid_pod(self):
        tool, _ = _tool()
        result = tool.get_logs_tail("Bad!", tail_lines=10)
        assert result.status == ResultStatus.FAILURE

    def test_valid(self):
        tool, conn = _tool()
        result = tool.get_logs_tail("my-pod", tail_lines=50)
        assert result.success is True
        cmd = conn.execute.call_args[0][0]
        assert "--tail=50" in cmd

    def test_valid_with_container(self):
        tool, conn = _tool()
        result = tool.get_logs_tail("my-pod", tail_lines=10, container="sidecar")
        assert result.success is True
        cmd = conn.execute.call_args[0][0]
        assert "-c sidecar" in cmd

    def test_invalid_container(self):
        tool, _ = _tool()
        result = tool.get_logs_tail("my-pod", tail_lines=10, container="BAD!")
        assert result.status == ResultStatus.FAILURE
