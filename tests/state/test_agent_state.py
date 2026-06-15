# SPDX-License-Identifier: Apache-2.0
"""Tests for state/agent_state.py — full branch coverage."""
import pytest
from state.agent_state import AgentState


class TestAgentState:
    def test_goal_required(self):
        s = AgentState(goal="Deploy cluster")
        assert s.goal == "Deploy cluster"

    def test_observations_default_empty(self):
        s = AgentState(goal="x")
        assert s.observations == []

    def test_observations_independent(self):
        s1 = AgentState(goal="a")
        s2 = AgentState(goal="b")
        s1.observations.append("obs1")
        assert s2.observations == []

    def test_observations_set(self):
        s = AgentState(goal="deploy", observations=["step1", "step2"])
        assert s.observations == ["step1", "step2"]

    def test_missing_goal_raises(self):
        with pytest.raises(TypeError):
            AgentState()
