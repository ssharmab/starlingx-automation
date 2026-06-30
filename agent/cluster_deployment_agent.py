# SPDX-License-Identifier: Apache-2.0

from agent.base_agent import BaseAgent

from agent.structs.goal import GoalStatus
from agent.structs.decision import Decision

from reasoning.llm_reasoner_base import BaseLLMReasoner as LLMReasoner

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
        reasoner: LLMReasoner
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
        Gather the current deployment state.

        Strategy:
        - On first iteration (no execution history), run the initial tool
          to get baseline information (e.g. inventory check).
        - On subsequent iterations, synthesize state from the last execution
          record so the reasoner has fresh context without re-running
          expensive tools unnecessarily.
        """

        # First observation: run the initial tool to get baseline data
        if not self._state.execution_history:
            if not self._registry.has(self._goal.initial_tool):
                return ToolResult(
                    success=False,
                    exit_code=1,
                    stderr=f"Initial tool '{self._goal.initial_tool}' is not registered",
                )

            tool = self._registry.get(self._goal.initial_tool)
            request = ToolRequest(
                correlation_id=self._correlation_id,
                parameters=self._goal.initial_tool_parameters,
            )
            return tool.execute(request)

        # Subsequent observations: summarize what we already know
        # from the last action's result, so the reasoner sees the
        # current state without re-invoking tools.
        last_record = self._state.execution_history[-1]

        return ToolResult(
            success=last_record.result.success,
            exit_code=last_record.result.exit_code,
            data={
                "last_tool": last_record.decision.tool,
                "last_tool_success": last_record.result.success,
                "last_tool_stdout": last_record.result.stdout,
                "last_tool_stderr": last_record.result.stderr,
                "last_tool_data": last_record.result.data,
                "total_actions_taken": len(self._state.execution_history),
            },
        )

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
        # If the reasoner (or human) explicitly signaled "done",
        # trust that decision and mark the goal completed.
        #
        if result.success and result.stdout == "Goal marked as done by reasoner.":
            return GoalStatus.COMPLETED

        #
        # If the reasoner (or human) explicitly signaled "fail",
        # mark the goal as failed.
        #
        if not result.success and result.stderr and result.stderr.startswith("Goal marked as failed"):
            return GoalStatus.FAILED

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

        print("  ")
        print(f"-> [evaluate_goal] observation = {observation}")
        print("  ")

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


# ---------------------------------------------------------------------------
# __main__ test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from unittest.mock import MagicMock

    # Ensure project root is importable
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from agent.structs.goal import Goal
    from agent.structs.execution_record import ExecutionRecord
    from state.agent_state import AgentState
    from registry.tool_registry import ToolRegistry
    from common.tool_definition import ToolDefinition

    print("=" * 60)
    print("  ClusterDeploymentAgent — test harness")
    print("=" * 60)

    # --- Helper: Build a fake tool ---
    def make_fake_tool(name, description, execute_result):
        tool = MagicMock()
        tool.name = name
        tool.description = description
        tool.definition = ToolDefinition(
            name=name, description=description
        )
        tool.execute.return_value = execute_result
        return tool

    # --- Helper: Build a fake reasoner ---
    def make_fake_reasoner(decision):
        reasoner = MagicMock()
        reasoner.decide.return_value = decision
        return reasoner

    # =========================================================================
    # Test 1: observe() when get_cluster_state is NOT registered
    # =========================================================================
    print("\n--- Test 1: observe() — get_cluster_state not registered ---")

    goal = Goal(name="deploy_cluster", 
                description="Deploy a StarlingX cluster",
                initial_tool="get_cluster_state", 
                success_criteria="Cluster is not deployed")
    
    registry = ToolRegistry()
    
    state = AgentState()
    
    reasoner = make_fake_reasoner(Decision(tool="noop", reason="x"))

    agent = ClusterDeploymentAgent(
        goal=goal,
        registry=registry,
        state=state,
        correlation_id="test-001",
        reasoner=reasoner
    )

    result = agent.observe()
    assert result.success is False
    assert "not registered" in result.stderr
    print(f"result {result}")
    print(f"  success: {result.success}")
    print(f"  stderr : {result.stderr}")
    print("  PASS")

    # =========================================================================
    # Test 2: observe() when get_cluster_state IS registered
    # =========================================================================
    print("\n--- Test 2: observe() — get_cluster_state registered ---")

    cluster_state_data = {
        "controllers": {"controller-0": "ready", "controller-1": "not_ready"},
        "kubernetes_ready": True,
        "custom_software_installed": False
    }
    fake_state_tool = make_fake_tool(
        "get_cluster_state",
        "Returns cluster state",
        ToolResult(success=True, exit_code=0, data=cluster_state_data)
    )

    registry2 = ToolRegistry()
    registry2.register(fake_state_tool)
    state2 = AgentState()

    agent2 = ClusterDeploymentAgent(
        goal=goal,
        registry=registry2,
        state=state2,
        correlation_id="test-002",
        reasoner=reasoner
    )

    result = agent2.observe()
    assert result.success is True
    assert result.data == cluster_state_data
    print(f"  success: {result.success}")
    print(f"  data   : {result.data}")
    print("  PASS")

    # =========================================================================
    # Test 3: reason() delegates to reasoner
    # =========================================================================
    print("\n--- Test 3: reason() delegates to LLM reasoner ---")

    expected_decision = Decision(
        tool="deploy_cluster",
        reason="Cluster not yet deployed",
        parameters={"target": "controller-0"}
    )
    reasoner3 = make_fake_reasoner(expected_decision)

    agent3 = ClusterDeploymentAgent(
        goal=goal,
        registry=registry2,
        state=state2,
        correlation_id="test-003",
        reasoner=reasoner3
    )

    observation = ToolResult(success=True, data=cluster_state_data)
    decision = agent3.reason(observation)
    assert decision.tool == "deploy_cluster"
    assert decision.reason == "Cluster not yet deployed"
    print(f"  tool   : {decision.tool}")
    print(f"  reason : {decision.reason}")
    print(f"  params : {decision.parameters}")
    print("  PASS")

    # =========================================================================
    # Test 4: evaluate_goal() — last action failed → IN_PROGRESS
    # =========================================================================
    print("\n--- Test 4: evaluate_goal() — action failed → IN_PROGRESS ---")

    failed_result = ToolResult(success=False, exit_code=1, stderr="timeout")
    status = agent3.evaluate_goal(failed_result)
    assert status == GoalStatus.IN_PROGRESS
    print(f"  status: {status.value}")
    print("  PASS")

    # =========================================================================
    # Test 5: evaluate_goal() — observe fails → BLOCKED
    # =========================================================================
    print("\n--- Test 5: evaluate_goal() — observe fails → BLOCKED ---")

    # Replace get_cluster_state tool to return failure
    broken_tool = make_fake_tool(
        "get_cluster_state",
        "Returns cluster state",
        ToolResult(success=False, exit_code=1, stderr="SSH timeout")
    )
    registry_broken = ToolRegistry()
    registry_broken.register(broken_tool)

    agent_broken = ClusterDeploymentAgent(
        goal=goal,
        registry=registry_broken,
        state=AgentState(),
        correlation_id="test-005",
        reasoner=reasoner3
    )

    success_result = ToolResult(success=True, exit_code=0)
    status = agent_broken.evaluate_goal(success_result)
    assert status == GoalStatus.BLOCKED
    print(f"  status: {status.value}")
    print("  PASS")

    # =========================================================================
    # Test 6: evaluate_goal() — all criteria met → COMPLETED
    # =========================================================================
    print("\n--- Test 6: evaluate_goal() — all criteria met → COMPLETED ---")

    complete_data = {
        "controllers": {"controller-0": "ready", "controller-1": "ready"},
        "kubernetes_ready": True,
        "custom_software_installed": True
    }
    complete_tool = make_fake_tool(
        "get_cluster_state",
        "Returns cluster state",
        ToolResult(success=True, exit_code=0, data=complete_data)
    )
    registry_complete = ToolRegistry()
    registry_complete.register(complete_tool)

    agent_complete = ClusterDeploymentAgent(
        goal=goal,
        registry=registry_complete,
        state=AgentState(),
        correlation_id="test-006",
        reasoner=reasoner3
    )

    status = agent_complete.evaluate_goal(
        ToolResult(success=True, exit_code=0)
    )
    assert status == GoalStatus.COMPLETED
    print(f"  status: {status.value}")
    print("  PASS")

    # =========================================================================
    # Test 7: evaluate_goal() — partial criteria → IN_PROGRESS
    # =========================================================================
    print("\n--- Test 7: evaluate_goal() — partial criteria → IN_PROGRESS ---")

    partial_data = {
        "controllers": {"controller-0": "ready", "controller-1": "not_ready"},
        "kubernetes_ready": True,
        "custom_software_installed": False
    }
    partial_tool = make_fake_tool(
        "get_cluster_state",
        "Returns cluster state",
        ToolResult(success=True, exit_code=0, data=partial_data)
    )
    registry_partial = ToolRegistry()
    registry_partial.register(partial_tool)

    agent_partial = ClusterDeploymentAgent(
        goal=goal,
        registry=registry_partial,
        state=AgentState(),
        correlation_id="test-007",
        reasoner=reasoner3
    )

    status = agent_partial.evaluate_goal(
        ToolResult(success=True, exit_code=0)
    )
    assert status == GoalStatus.IN_PROGRESS
    print(f"  status: {status.value}")
    print("  PASS")

    # =========================================================================
    # Test 8: act() — tool not registered
    # =========================================================================
    print("\n--- Test 8: act() — tool not registered ---")

    agent_empty = ClusterDeploymentAgent(
        goal=goal,
        registry=ToolRegistry(),
        state=AgentState(),
        correlation_id="test-008",
        reasoner=reasoner3
    )

    bad_decision = Decision(tool="nonexistent_tool", reason="test")
    result = agent_empty.act(bad_decision)
    assert result.success is False
    assert "not registered" in result.stderr
    print(f"  success: {result.success}")
    print(f"  stderr : {result.stderr}")
    print("  PASS")

    # =========================================================================
    # Test 9: act() — tool registered and executes
    # =========================================================================
    print("\n--- Test 9: act() — tool registered and executes ---")

    deploy_tool = make_fake_tool(
        "deploy_cluster",
        "Deploys cluster",
        ToolResult(success=True, exit_code=0, stdout="deployed")
    )
    registry_with_deploy = ToolRegistry()
    registry_with_deploy.register(deploy_tool)

    agent_act = ClusterDeploymentAgent(
        goal=goal,
        registry=registry_with_deploy,
        state=AgentState(),
        correlation_id="test-009",
        reasoner=reasoner3
    )

    good_decision = Decision(
        tool="deploy_cluster",
        reason="need to deploy",
        parameters={"target": "controller-0"}
    )
    result = agent_act.act(good_decision)
    assert result.success is True
    assert result.stdout == "deployed"
    print(f"  success: {result.success}")
    print(f"  stdout : {result.stdout}")
    print("  PASS")

    # =========================================================================
    # Test 10: Full run() loop — completes in 1 iteration
    # =========================================================================
    print("\n--- Test 10: run() — full loop completes in 1 iteration ---")

    # Reasoner returns "done" decision that targets a tool returning success
    done_tool = make_fake_tool(
        "get_cluster_state",
        "Returns cluster state",
        ToolResult(success=True, exit_code=0, data=complete_data)
    )
    finish_tool = make_fake_tool(
        "done",
        "Goal complete",
        ToolResult(success=True, exit_code=0, stdout="done")
    )
    registry_run = ToolRegistry()
    registry_run.register(done_tool)
    registry_run.register(finish_tool)

    done_reasoner = make_fake_reasoner(
        Decision(tool="done", reason="goal achieved")
    )

    agent_run = ClusterDeploymentAgent(
        goal=goal,
        registry=registry_run,
        state=AgentState(),
        correlation_id="test-010",
        reasoner=done_reasoner
    )

    final_status = agent_run.run()
    assert final_status == GoalStatus.COMPLETED
    print(f"  final_status : {final_status.value}")
    print(f"  iterations   : {len(agent_run._state.execution_history)}")
    print("  PASS")

    # =========================================================================
    # Test 11: run() — max iterations reached → BLOCKED
    # =========================================================================
    print("\n--- Test 11: run() — max iterations → BLOCKED ---")

    # Tool always returns partial state so goal never completes
    stuck_tool = make_fake_tool(
        "get_cluster_state",
        "Returns cluster state",
        ToolResult(success=True, exit_code=0, data=partial_data)
    )
    noop_tool = make_fake_tool(
        "noop",
        "Does nothing",
        ToolResult(success=True, exit_code=0)
    )
    registry_stuck = ToolRegistry()
    registry_stuck.register(stuck_tool)
    registry_stuck.register(noop_tool)

    stuck_reasoner = make_fake_reasoner(
        Decision(tool="noop", reason="waiting")
    )

    agent_stuck = ClusterDeploymentAgent(
        goal=goal,
        registry=registry_stuck,
        state=AgentState(),
        correlation_id="test-011",
        reasoner=stuck_reasoner
    )
    # Reduce max iterations for speed
    agent_stuck.MAX_ITERATIONS = 3

    final_status = agent_stuck.run()
    assert final_status == GoalStatus.BLOCKED
    print(f"  final_status : {final_status.value}")
    print(f"  iterations   : {len(agent_stuck._state.execution_history)}")
    print("  PASS")

    print("\n" + "=" * 60)
    print("  All ClusterDeploymentAgent tests complete.")
    print("=" * 60)
