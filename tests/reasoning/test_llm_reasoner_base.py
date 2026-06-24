# SPDX-License-Identifier: Apache-2.0
"""Tests for reasoning/llm_reasoner_base.py — full branch coverage."""
import pytest

from agent.structs.goal import Goal
from agent.structs.decision import Decision
from agent.structs.execution_record import ExecutionRecord
from common.tool_result import ToolResult
from tools.tool_definition import ToolDefinition
from reasoning.llm_reasoner_base import BaseLLMReasoner


class TestBaseLLMReasonerAbstract:
    """Verify that BaseLLMReasoner enforces the abstract contract."""

    def test_cannot_instantiate_directly(self):
        """BaseLLMReasoner is abstract — instantiation must raise TypeError."""
        with pytest.raises(TypeError, match="abstract"):
            BaseLLMReasoner()

    def test_subclass_without_decide_raises(self):
        """A subclass that doesn't implement decide() cannot be instantiated."""

        class IncompleteReasoner(BaseLLMReasoner):
            pass

        with pytest.raises(TypeError, match="abstract"):
            IncompleteReasoner()

    def test_concrete_subclass_can_be_instantiated(self):
        """A subclass implementing decide() can be instantiated."""

        class ConcreteReasoner(BaseLLMReasoner):
            def decide(self, goal, observation, execution_history, tools):
                return Decision(tool="noop", reason="test", parameters={})

        reasoner = ConcreteReasoner()
        assert reasoner is not None

    def test_concrete_subclass_decide_returns_decision(self):
        """decide() must return a Decision object."""

        class ConcreteReasoner(BaseLLMReasoner):
            def decide(self, goal, observation, execution_history, tools):
                return Decision(
                    tool=goal.name,
                    reason="because",
                    parameters={"key": "value"}
                )

        reasoner = ConcreteReasoner()
        goal = Goal(name="test_tool")
        observation = ToolResult(success=True, exit_code=0)
        history = []
        tools = []

        result = reasoner.decide(goal, observation, history, tools)

        assert isinstance(result, Decision)
        assert result.tool == "test_tool"
        assert result.reason == "because"
        assert result.parameters == {"key": "value"}

    def test_decide_receives_execution_history(self):
        """decide() should have access to full execution history."""

        received_history = []

        class HistoryReasoner(BaseLLMReasoner):
            def decide(self, goal, observation, execution_history, tools):
                received_history.extend(execution_history)
                return Decision(tool="x", reason="y", parameters={})

        reasoner = HistoryReasoner()
        goal = Goal(name="deploy")
        obs = ToolResult(success=True)
        record = ExecutionRecord(
            observation=ToolResult(success=True),
            decision=Decision(tool="a", reason="b", parameters={}),
            result=ToolResult(success=True),
        )

        reasoner.decide(goal, obs, [record], [])

        assert len(received_history) == 1
        assert received_history[0].decision.tool == "a"

    def test_decide_receives_tool_definitions(self):
        """decide() should have access to available tool definitions."""

        received_tools = []

        class ToolAwareReasoner(BaseLLMReasoner):
            def decide(self, goal, observation, execution_history, tools):
                received_tools.extend(tools)
                return Decision(tool="chosen", reason="best fit", parameters={})

        reasoner = ToolAwareReasoner()
        tool_def = ToolDefinition(
            name="get_nodes",
            description="Returns cluster nodes",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )

        reasoner.decide(
            Goal(name="check_health"),
            ToolResult(success=True),
            [],
            [tool_def],
        )

        assert len(received_tools) == 1
        assert received_tools[0].name == "get_nodes"

    def test_is_abstract_base_class(self):
        """BaseLLMReasoner should be an ABC."""
        from abc import ABC
        assert issubclass(BaseLLMReasoner, ABC)
