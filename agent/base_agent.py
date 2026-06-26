# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod

from state.agent_state import AgentState
from agent.structs.goal import Goal
from agent.structs.goal import GoalStatus
from agent.structs.decision import Decision
from agent.structs.execution_record import ExecutionRecord

from common.tool_request import ToolRequest
from common.tool_result import ToolResult

from registry.tool_registry import ToolRegistry


class BaseAgent(ABC):

    MAX_ITERATIONS = 20

    def __init__(
        self,
        goal: Goal,
        registry: ToolRegistry,
        state: AgentState,
        correlation_id: str
    ):
        self._goal = goal
        self._registry = registry
        self._state = state
        self._correlation_id = correlation_id

    @abstractmethod
    def observe(self) -> ToolResult:
        pass

    @abstractmethod
    def reason(
        self,
        observation: ToolResult
    ) -> Decision:
        pass

    @abstractmethod
    def evaluate_goal(
        self,
        result: ToolResult
    ) -> GoalStatus:
        pass

    def act(
        self,
        decision: Decision
    ) -> ToolResult:

        if not self._registry.has(
            decision.tool
        ):
            return ToolResult(
                success=False,
                exit_code=1,
                stderr=(
                    f"Tool '{decision.tool}' "
                    "is not registered"
                )
            )

        tool = self._registry.get(
            decision.tool
        )

        request = ToolRequest(
            correlation_id=self._correlation_id,
            parameters=decision.parameters
        )

        return tool.execute(request)


    def _record_execution(
        self,
        observation: ToolResult,
        decision: Decision,
        result: ToolResult
    ) -> None:

        self._state.execution_history.append(
            ExecutionRecord(
                observation=observation,
                decision=decision,
                result=result
            )
        )

    def run(self) -> GoalStatus:

        for _ in range(self.MAX_ITERATIONS):

            observation = self.observe()

            decision = self.reason(
                observation
            )

            print(f"reason decision: {decision}")

            result = self.act(
                decision
            )

            print(f" result of act {result}")

            self._record_execution(
                observation,
                decision,
                result
            )

            print(f"execution record is {self._state.execution_history}")

            status = self.evaluate_goal(
                result
            )

            self._state.goal_status = status

            print(f" State after evaluate_goal is {self._state}")

            if status in (
                GoalStatus.COMPLETED,
                GoalStatus.FAILED,
                GoalStatus.BLOCKED
            ):
                return status

        self._state.goal_status = (
            GoalStatus.BLOCKED
        )

        return GoalStatus.BLOCKED