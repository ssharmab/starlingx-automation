# SPDX-License-Identifier: Apache-2.0
"""
goal.py
------------------
Represents a goal that an agent can pursue.
"""

from dataclasses import dataclass, field
from enum import Enum


class GoalStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class Goal:
    """
    Represents a goal that an agent can pursue.
    """

    name: str

    description: str = field(default="")

    initial_tool: str = field(default="")

    initial_tool_parameters: dict(Any, Any) = field(default=None)
    
    success_criteria: str = field(default="")

    def __str__(self) -> str:
        return self.name