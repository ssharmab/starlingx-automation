# SPDX-License-Identifier: Apache-2.0
"""
LLM-backed reasoning engine.

Why this exists:

- Separates reasoning from agent orchestration.
- Allows multiple agents to share the same reasoning engine.
"""

from abc import ABC, abstractmethod

from agent.structs.goal import Goal
from agent.structs.decision import Decision
from agent.structs.execution_record import ExecutionRecord

from common.tool_result import ToolResult

from common.tool_definition import ToolDefinition


class BaseLLMReasoner(ABC):

    @abstractmethod
    def decide(
        self,
        goal: Goal,
        observation: ToolResult,
        execution_history: list[ExecutionRecord],
        tools: list[ToolDefinition]
    ) -> Decision:
        pass