# SPDX-License-Identifier: Apache-2.0
"""Tests for common/tool_result.py — full branch coverage."""
import pytest
from common.tool_result import ToolResult


class TestToolResult:
    def test_defaults(self):
        """Test default values for ToolResult."""
        r = ToolResult()
        assert r.success is False
        assert r.exit_code == 0
        assert r.stdout == ""
        assert r.stderr == ""
        assert r.data == {}
        assert r.error_message == ""
        assert r.timestamp == ""
        assert r.metadata == {}
        assert r.duration_seconds == 0.0

    def test_success_true(self):
        """Test creating a successful ToolResult."""
        r = ToolResult(success=True, exit_code=0)
        assert r.success is True

    def test_success_false(self):
        """Test creating a failed ToolResult."""
        r = ToolResult(success=False, exit_code=1, error_message="Command failed")
        assert r.success is False
        assert r.exit_code == 1
        assert r.error_message == "Command failed"

    def test_with_stdout_stderr(self):
        """Test ToolResult with standard output and error."""
        r = ToolResult(
            success=True,
            exit_code=0,
            stdout="output line 1\noutput line 2",
            stderr=""
        )
        assert r.stdout == "output line 1\noutput line 2"
        assert r.stderr == ""

    def test_with_data(self):
        """Test ToolResult with structured data."""
        data = {"nodes": 3, "pods": 12, "services": 5}
        r = ToolResult(success=True, exit_code=0, data=data)
        assert r.data == data

    def test_with_metadata(self):
        """Test ToolResult with metadata."""
        metadata = {"namespace": "default", "cluster": "prod"}
        r = ToolResult(success=True, exit_code=0, metadata=metadata)
        assert r.metadata == metadata

    def test_with_timestamp_and_duration(self):
        """Test ToolResult with timestamp and duration."""
        r = ToolResult(
            success=True,
            exit_code=0,
            timestamp="2026-06-24T10:30:00Z",
            duration_seconds=1.234
        )
        assert r.timestamp == "2026-06-24T10:30:00Z"
        assert r.duration_seconds == 1.234

    def test_all_fields(self):
        """Test ToolResult with all fields populated."""
        r = ToolResult(
            success=True,
            exit_code=0,
            stdout="pod running",
            stderr="",
            data={"status": "Running"},
            error_message="",
            timestamp="2026-06-24T10:30:00Z",
            metadata={"namespace": "default"},
            duration_seconds=0.5
        )
        assert r.success is True
        assert r.exit_code == 0
        assert r.stdout == "pod running"
        assert r.stderr == ""
        assert r.data == {"status": "Running"}
        assert r.error_message == ""
        assert r.timestamp == "2026-06-24T10:30:00Z"
        assert r.metadata == {"namespace": "default"}
        assert r.duration_seconds == 0.5

    def test_error_result(self):
        """Test creating an error result."""
        r = ToolResult(
            success=False,
            exit_code=-1,
            stderr="connection timeout",
            error_message="Failed to connect to host"
        )
        assert r.success is False
        assert r.exit_code == -1
        assert r.stderr == "connection timeout"
        assert r.error_message == "Failed to connect to host"
