# SPDX-License-Identifier: Apache-2.0
"""Tests for tools/rvmc/base.py — full branch coverage."""
import pytest
from tools.rvmc.base import RvmcBaseTool
from tools.rvmc.bmc_target import BmcTarget
from utils.tool_result import ToolResult, ResultStatus


def _target():
    return BmcTarget(
        address="1.2.3.4",
        username="admin",
        password="secret",
        image="http://10.0.0.1/boot.iso",
        target_name="test",
    )


class TestRvmcBaseTool:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError, match="abstract"):
            RvmcBaseTool(_target())

    def test_wrong_target_type_raises(self):
        class Concrete(RvmcBaseTool):
            name = "test"
            description = "test"
            def execute(self) -> ToolResult:
                return ToolResult(status=ResultStatus.SUCCESS, exit_code=0)

        with pytest.raises(TypeError, match="BmcTarget"):
            Concrete("not-a-bmc-target")

    def test_concrete_subclass_stores_target(self):
        class Concrete(RvmcBaseTool):
            name = "test"
            description = "test"
            def execute(self) -> ToolResult:
                return ToolResult(status=ResultStatus.SUCCESS, exit_code=0)

        t = _target()
        obj = Concrete(t)
        assert obj.target is t

    def test_concrete_subclass_execute_returns_tool_result(self):
        class Concrete(RvmcBaseTool):
            name = "test"
            description = "test"
            def execute(self) -> ToolResult:
                return ToolResult(status=ResultStatus.SUCCESS, exit_code=0)

        result = Concrete(_target()).execute()
        assert isinstance(result, ToolResult)
        assert result.success is True

    def test_subclass_without_execute_raises(self):
        class Incomplete(RvmcBaseTool):
            name = "incomplete"
            description = "missing execute"

        with pytest.raises(TypeError, match="abstract"):
            Incomplete(_target())

    def test_name_and_description_defaults(self):
        class Concrete(RvmcBaseTool):
            def execute(self) -> ToolResult:
                return ToolResult(status=ResultStatus.SUCCESS, exit_code=0)

        obj = Concrete(_target())
        assert obj.name == ""
        assert obj.description == ""
