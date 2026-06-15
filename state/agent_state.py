# SPDX-License-Identifier: Apache-2.0
"""
agent_state.py
--------------
Standard agent state object for agents.

Why this exists:
- The state of the agent and the goals need to be preserved.

"""
from dataclasses import dataclass, field

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
    goals : list[str]
    observations: list[str] = field(default_factory=list)
