# SPDX-License-Identifier: Apache-2.0
"""
agent_state.py
--------------
Standard agent state object for agents.

Why this exists:
- The state of the agent and the goals need to be preserved.

"""
from dataclasses import dataclass, field
from common.tool_result import ToolResult
from enum import Enum


class GoalStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class AgentState:
    """
    Standard state object for agentic workflows.

    Attributes:
        goals: List of goals to be achieved.
        current_goal: The goal currently being worked on.
        completed_goals: List of goals that have been completed.
        failed_goals: List of goals that have failed.
        task_history: List of tasks that have been executed.
        current_task: The task currently being executed.
        task_results: Results of the tasks that have been executed.
    """
    goals : list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    conclusions: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    goal_status: dict[str, GoalStatus] = field(default_factory=dict)
    task_history: list[str] = field(default_factory=list)
    current_task: str | None = None
    current_goal: str | None = None
    ####### TODO: to maintain a history of tool results dict[str, list[ToolResult]] is better
    task_results: dict[str, ToolResult] = field(default_factory=dict)
    ####### END TODO