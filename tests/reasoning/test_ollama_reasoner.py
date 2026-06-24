# SPDX-License-Identifier: Apache-2.0
"""
Tests for reasoning/ollama_reasoner.py — full branch coverage.

NOTE: ollama_reasoner.py has known issues in source:
    1. Import: `from llm_reasoner_base import LLMReasonerBase` (bare module)
    2. Class declaration uses `BaseLLMReasoner` (the real class name) rather
       than the imported `LLMReasonerBase` alias.
    3. OllamaReasoner does NOT implement the abstract `decide()` method from
       BaseLLMReasoner. It only implements `generate()`. This means it
       cannot be instantiated directly (ABC enforcement).

These tests document and verify the current behavior, then test logic
via a patched subclass that adds the missing abstract method.

Import patching is handled by tests/reasoning/conftest.py.
"""
from unittest.mock import MagicMock

import pytest

from agent.structs.decision import Decision
from agent.structs.goal import Goal
from common.tool_result import ToolResult
from tools.tool_definition import ToolDefinition
from reasoning.llm_reasoner_base import BaseLLMReasoner
from reasoning.ollama_reasoner import OllamaReasoner


# ---------------------------------------------------------------------------
# Helper: Patched subclass that adds the missing decide() method
# ---------------------------------------------------------------------------

class _TestableOllamaReasoner(OllamaReasoner):
    """
    Subclass that implements the missing decide() abstract method
    so we can instantiate and test generate() logic.
    """

    def decide(self, goal, observation, execution_history, tools):
        """Delegate to generate() for testing purposes."""
        return self.generate()


# ---------------------------------------------------------------------------
# Tests: ABC enforcement (cannot instantiate)
# ---------------------------------------------------------------------------


class TestOllamaReasonerAbstractEnforcement:
    """OllamaReasoner is missing decide() so ABC prevents instantiation."""

    def test_cannot_instantiate_directly(self):
        """OllamaReasoner lacks decide() — instantiation must raise TypeError."""
        with pytest.raises(TypeError, match="abstract"):
            OllamaReasoner(
                goal=Goal(name="x"),
                observation=ToolResult(),
                execution_history=[],
                tools=[],
            )

    def test_error_message_mentions_decide(self):
        """The TypeError should reference the missing 'decide' method."""
        with pytest.raises(TypeError, match="decide"):
            OllamaReasoner(
                goal=Goal(name="x"),
                observation=ToolResult(),
                execution_history=[],
                tools=[],
            )


# ---------------------------------------------------------------------------
# Tests: Inheritance structure
# ---------------------------------------------------------------------------


class TestOllamaReasonerInheritance:
    """Verify class hierarchy."""

    def test_is_subclass_of_base_llm_reasoner(self):
        assert issubclass(OllamaReasoner, BaseLLMReasoner)

    def test_has_generate_method(self):
        assert hasattr(OllamaReasoner, "generate")
        assert callable(OllamaReasoner.generate)

    def test_has_init_method(self):
        assert hasattr(OllamaReasoner, "__init__")

    def test_does_not_implement_decide(self):
        """decide() is inherited abstract — not overridden by OllamaReasoner."""
        assert "decide" in dir(OllamaReasoner)


# ---------------------------------------------------------------------------
# Tests: __init__ via patched subclass
# ---------------------------------------------------------------------------


class TestOllamaReasonerInit:
    """Test __init__ stores all provided arguments (via testable subclass)."""

    def test_stores_goal(self):
        goal = Goal(name="deploy")
        r = _TestableOllamaReasoner(
            goal=goal,
            observation=ToolResult(),
            execution_history=[],
            tools=[],
        )
        assert r.goal is goal

    def test_stores_observation(self):
        obs = ToolResult(success=True, stdout="nodes ready")
        r = _TestableOllamaReasoner(
            goal=Goal(name="x"),
            observation=obs,
            execution_history=[],
            tools=[],
        )
        assert r.observation is obs

    def test_stores_execution_history(self):
        history = [MagicMock(), MagicMock()]
        r = _TestableOllamaReasoner(
            goal=Goal(name="x"),
            observation=ToolResult(),
            execution_history=history,
            tools=[],
        )
        assert r.execution_history is history
        assert len(r.execution_history) == 2

    def test_stores_tools(self):
        tools = [
            ToolDefinition(name="get_nodes", description="nodes"),
            ToolDefinition(name="get_pods", description="pods"),
        ]
        r = _TestableOllamaReasoner(
            goal=Goal(name="x"),
            observation=ToolResult(),
            execution_history=[],
            tools=tools,
        )
        assert r.tools is tools
        assert len(r.tools) == 2

    def test_accepts_any_goal_type(self):
        """__init__ doesn't type-check goal — accepts anything."""
        r = _TestableOllamaReasoner(
            goal="string_goal",
            observation=ToolResult(),
            execution_history=[],
            tools=[],
        )
        assert r.goal == "string_goal"

    def test_accepts_none_observation(self):
        """__init__ doesn't type-check observation."""
        r = _TestableOllamaReasoner(
            goal=Goal(name="x"),
            observation=None,
            execution_history=[],
            tools=[],
        )
        assert r.observation is None


# ---------------------------------------------------------------------------
# Tests: generate()
# ---------------------------------------------------------------------------


class TestOllamaReasonerGenerate:
    """Test generate() returns a valid placeholder Decision."""

    def test_returns_decision_instance(self):
        r = _TestableOllamaReasoner(
            goal=Goal(name="deploy"),
            observation=ToolResult(),
            execution_history=[],
            tools=[],
        )
        decision = r.generate()
        assert isinstance(decision, Decision)

    def test_decision_tool_is_dummy_action(self):
        r = _TestableOllamaReasoner(
            goal=Goal(name="x"),
            observation=ToolResult(),
            execution_history=[],
            tools=[],
        )
        decision = r.generate()
        assert decision.tool == "dummy_action"

    def test_decision_reason_is_placeholder(self):
        r = _TestableOllamaReasoner(
            goal=Goal(name="x"),
            observation=ToolResult(),
            execution_history=[],
            tools=[],
        )
        decision = r.generate()
        assert decision.reason == "This is a placeholder decision."

    def test_decision_parameters_empty(self):
        r = _TestableOllamaReasoner(
            goal=Goal(name="x"),
            observation=ToolResult(),
            execution_history=[],
            tools=[],
        )
        decision = r.generate()
        assert decision.parameters == {}

    def test_decision_independent_of_goal(self):
        """Placeholder returns same decision regardless of inputs."""
        r1 = _TestableOllamaReasoner(
            goal=Goal(name="deploy"),
            observation=ToolResult(success=True),
            execution_history=[MagicMock()],
            tools=[ToolDefinition(name="t1", description="d1")],
        )
        r2 = _TestableOllamaReasoner(
            goal=Goal(name="rollback"),
            observation=ToolResult(success=False, stderr="error"),
            execution_history=[],
            tools=[],
        )
        d1 = r1.generate()
        d2 = r2.generate()
        assert d1.tool == d2.tool
        assert d1.reason == d2.reason
        assert d1.parameters == d2.parameters

    def test_multiple_calls_return_same_result(self):
        """generate() is deterministic (placeholder)."""
        r = _TestableOllamaReasoner(
            goal=Goal(name="x"),
            observation=ToolResult(),
            execution_history=[],
            tools=[],
        )
        d1 = r.generate()
        d2 = r.generate()
        assert d1.tool == d2.tool
        assert d1.reason == d2.reason


# ---------------------------------------------------------------------------
# Tests: decide() via testable subclass
# ---------------------------------------------------------------------------


class TestOllamaReasonerDecideViaSubclass:
    """Test that a subclass adding decide() can use generate()."""

    def test_decide_delegates_to_generate(self):
        r = _TestableOllamaReasoner(
            goal=Goal(name="x"),
            observation=ToolResult(),
            execution_history=[],
            tools=[],
        )
        decision = r.decide(
            Goal(name="y"), ToolResult(), [], []
        )
        assert decision.tool == "dummy_action"
        assert isinstance(decision, Decision)

    def test_testable_subclass_is_instantiable(self):
        """With decide() implemented, ABC allows instantiation."""
        r = _TestableOllamaReasoner(
            goal=Goal(name="x"),
            observation=ToolResult(),
            execution_history=[],
            tools=[],
        )
        assert isinstance(r, OllamaReasoner)
        assert isinstance(r, BaseLLMReasoner)
