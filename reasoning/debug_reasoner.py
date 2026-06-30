# SPDX-License-Identifier: Apache-2.0
"""
debug_reasoner.py
-----------------
A reasoner that delegates decisions to a human via the DebugClient.
Uses the same interface as OllamaReasoner but instead of calling an LLM,
it waits for human input through the chat UI.
"""

import json

from reasoning.llm_reasoner_base import BaseLLMReasoner

from client.debug_client import DebugClient

from agent.structs.goal import Goal
from agent.structs.decision import Decision
from agent.structs.execution_record import ExecutionRecord

from common.tool_result import ToolResult
from common.tool_definition import ToolDefinition


class DebugReasoner(BaseLLMReasoner):
    """
    Reasoner that presents context to a human operator and waits
    for them to manually enter the next decision (tool + reason + params).
    """

    def __init__(self, client: DebugClient):
        self._client = client

    def decide(
        self,
        goal: Goal,
        observation: ToolResult,
        execution_history: list[ExecutionRecord],
        tools: list[ToolDefinition],
    ) -> Decision:

        prompt = self._build_prompt(goal, observation, execution_history, tools)

        # This blocks until the human responds via the UI
        response = self._client.generate(prompt)

        decision_json = json.loads(response)

        print(f"[DebugReasoner] decision_json: {decision_json}")
        return Decision(
            tool=decision_json["tool"],
            reason=decision_json["reason"],
            parameters=decision_json.get("parameters", {}),
        )

    def _build_prompt(
        self,
        goal: Goal,
        observation: ToolResult,
        execution_history: list[ExecutionRecord],
        tools: list[ToolDefinition],
    ) -> str:
        tool_names = [t.name for t in tools]
        history_summary = ""
        for i, rec in enumerate(execution_history[-5:], 1):
            history_summary += (
                f"  {i}. tool={rec.decision.tool}, "
                f"reason={rec.decision.reason}, "
                f"success={rec.result.success}\n"
            )

        return (
            f"=== DEBUG MODE: Human Decision Required ===\n\n"
            f"Goal: {goal.description}\n\n"
            f"Current Observation:\n"
            f"  success: {observation.success}\n"
            f"  data: {observation.data}\n"
            f"  stdout: {observation.stdout}\n"
            f"  stderr: {observation.stderr}\n\n"
            f"Recent Execution History:\n{history_summary or '  (none)'}\n\n"
            f"Available Tools: {tool_names}\n\n"
            f"Enter your decision as JSON with keys: tool, reason, parameters"
        )
