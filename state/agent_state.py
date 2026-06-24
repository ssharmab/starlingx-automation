# SPDX-License-Identifier: Apache-2.0
"""
Runtime state for a single agent execution.
"""

from dataclasses import dataclass, field

from agent.structs.goal import GoalStatus
from agent.structs.execution_record import ExecutionRecord


@dataclass(slots=True)
class AgentState:
    """
    Runtime state for an agent.

    Why this exists:

    - Tracks overall goal progress.
    - Preserves execution history.
    - Tracks unanswered questions.
    """

    goal_status: GoalStatus = GoalStatus.PENDING

    execution_history: list[ExecutionRecord] = field(
        default_factory=list
    )

    pending_questions: list[str] = field(
        default_factory=list
    )