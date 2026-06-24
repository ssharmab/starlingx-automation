# SPDX-License-Identifier: Apache-2.0

from agent.base_agent import BaseAgent

from agent.structs.goal import GoalStatus
from agent.structs.decision import Decision

from reasoning.llm_reasoner_base import LLMReasonerBase

from common.tool_request import ToolRequest
from common.tool_result import ToolResult


class ClusterDeploymentAgent(BaseAgent):
    """
    Deploys a StarlingX cluster.

    The agent itself contains very little deployment logic.
    It gathers observations, delegates reasoning to the
    LLMReasoner, executes tools, and evaluates progress.
    """

    def __init__(
        self,
        goal,
        registry,
        state,
        correlation_id,
        reasoner: LLMReasonerBase
    ):
        super().__init__(
            goal=goal,
            registry=registry,
            state=state,
            correlation_id=correlation_id
        )

        self._reasoner = reasoner
        

    def observe(self) -> ToolResult:
        """
        Gather the latest cluster state.
        """

        if not self._registry.has(
            "get_cluster_state"
        ):
            return ToolResult(
                success=False,
                exit_code=1,
                stderr=(
                    "get_cluster_state tool "
                    "is not registered"
                )
            )

        tool = self._registry.get(
            "get_cluster_state"
        )

        request = ToolRequest(
            correlation_id=self._correlation_id
        )

        return tool.execute(request)

    def reason(
        self,
        observation: ToolResult
    ) -> Decision:

        return self._reasoner.decide(
            goal=self._goal,
            observation=observation,
            execution_history=
                self._state.execution_history,
            tools=
                self._registry.tool_definitions()
        )

    def evaluate_goal(
        self,
        result: ToolResult
    ) -> GoalStatus:

        #
        # If the last action failed,
        # allow the agent to reason again.
        #
        # The LLM may choose:
        #
        # - retry
        # - collect diagnostics
        # - ask user
        #
        if not result.success:
            return GoalStatus.IN_PROGRESS

        #
        # Re-observe cluster state.
        #
        observation = self.observe()

        if not observation.success:
            return GoalStatus.BLOCKED

        state = observation.data

        #
        # Minimal success criteria.
        #
        controllers = state.get(
            "controllers",
            {}
        )

        controller_0_ready = (
            controllers.get(
                "controller-0"
            ) == "ready"
        )

        controller_1_ready = (
            controllers.get(
                "controller-1"
            ) == "ready"
        )

        kubernetes_ready = (
            state.get(
                "kubernetes_ready",
                False
            )
        )

        custom_software_installed = (
            state.get(
                "custom_software_installed",
                False
            )
        )

        if (
            controller_0_ready
            and controller_1_ready
            and kubernetes_ready
            and custom_software_installed
        ):
            return GoalStatus.COMPLETED

        return GoalStatus.IN_PROGRESS