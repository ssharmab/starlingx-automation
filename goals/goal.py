# SPDX-License-Identifier: Apache-2.0
"""
goal.py
------------------
Represents a goal that the agent can pursue.
"""
from dataclasses import dataclass, field
from enum import Enum

class GoalStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class Goal:
    """
    Represents a goal that the agent can pursue.
    """
    name: str
    description: str = field(default="")
    initial_tool: str = field(default="")
    # TODO: success_criteria: Callable or success_criteria: GoalEvaluator or similar is better than a string, but for now we can assume that the agent will use the description field to determine if the goal has been achieved or not. In the future, we may want to add a more structured way to define success criteria.
    success_criteria: str = field(default="")
    
    # TODO: add max_retries or similar field to indicate how many times the agent should retry if it fails to achieve the goal. For now, we can assume that the agent will keep trying indefinitely until it succeeds, but in the future we may want to add a limit to prevent infinite loops.
    # max_retries: int = field(default=0)


    def __str__(self):
        return self.description