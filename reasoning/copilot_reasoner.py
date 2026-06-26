# reasoning/copilot_reasoner.py

import json

from reasoning.llm_reasoner_base import BaseLLMReasoner

from client.base_llm_client import BaseLLMClient

from agent.structs.goal import Goal
from agent.structs.decision import Decision
from agent.structs.execution_record import ExecutionRecord
from agent.structs.tool_definition import ToolDefinition

from common.tool_result import ToolResult


class CopilotReasoner(
    BaseLLMReasoner
):

    def __init__(
        self,
        client: BaseLLMClient
    ):
        self._client = client

    def decide(
        self,
        goal: Goal,
        observation: ToolResult,
        execution_history: list[ExecutionRecord],
        tools: list[ToolDefinition]
    ) -> Decision:

        prompt = self._build_prompt(
            goal,
            observation,
            execution_history,
            tools
        )

        response = self._client.generate(
            prompt
        )

        decision_json = json.loads(
            response
        )

        return Decision(
            tool=decision_json["tool"],
            reason=decision_json["reason"],
            parameters=decision_json.get(
                "parameters",
                {}
            )
        )

    def _build_prompt(
        self,
        goal,
        observation,
        execution_history,
        tools
    ) -> str:

        return f"""
You are an autonomous cluster deployment agent.

Your responsibility is to determine the SINGLE best next action required
to achieve the deployment goal.

Goal:
{goal.description}

Current Observation:
{observation.data}

Execution History:
{execution_history}

Available Tools:
{tools}

Rules:

- If cluster_state is "not_deployed", deployment may be started.
- If cluster_state is "deploying", do not start another deployment.
- If cluster_state is "deploying", prefer monitoring tools.
- If cluster_state is "deployed", deployment tools should not be used.
- If the goal is already satisfied by the current observation,
  you MUST return "done" as the tool with a reason explaining why.
- If the goal cannot be achieved due to a permanent failure,
  return "fail" as the tool with a reason explaining why.

Decision Tree (follow in order):

Step 1: Is the goal already satisfied?
  - The goal says "deploy" and cluster_state is "succeeded" or "deployed" → return "done"
  - The goal says "deploy" and cluster_state is "not_deployed" → go to Step 2
  - The goal says "deploy" and cluster_state is "deploying" → return "monitor_cluster"
  - The goal says "deploy" and cluster_state is "error" -> return "investigate_failure"
Step 2: Select the tool that advances the goal.
Step 3: If no tool advances the goal, return "done".

Synonyms:
- "not deployed" has synonyms "deploy", "create", "provision"
- "deployed" has synonyms "done", "provisioned", "created", "succeeded"
- "deploying" has synonyms "in progress", "doing", "creating", "provisioning"
- "error" has synonyms "failure", "failed"

All tenses of the words above (that is past and present and their derivatives) are valid.

Instructions:

1. Analyze the current observation.
2. Consider the goal and execution history.
3. If the goal is already satisfied, return "done" as the tool.
4. Select exactly ONE tool from the Available Tools list, or "done", or "fail".
5. Do not invent tool names beyond "done" and "fail".
6. Use only tools that are explicitly listed.
7. If additional information is required before proceeding,
   select the tool that obtains that information.
8. Explain why the selected tool is the best next action.
9. Generate any required tool parameters.
10. Return ONLY valid JSON.
11. Do not include markdown, explanations, code fences, or any text
    outside the JSON object.

Expected Output Format:

CRITICAL: The "tool" field must be the NEXT ACTION to perform, not the goal.
If the goal is already achieved, "tool" MUST be "done".

Example — goal achieved:
{{
  "tool": "done",
  "reason": "cluster_state is succeeded, goal is satisfied",
  "parameters": {{}}
}}

Example — goal not yet achieved:
{{
  "tool": "deploy_cluster",
  "reason": "cluster_state is not_deployed, deployment needed",
  "parameters": {{}}
}}

Your response:
"""
    
if __name__ == "__main__":
    from client.copilot_client import CopilotClient

    endpoint = "<azure-openai-endpoint>"
    api_key = "<api-key>"
    model = "gpt-4"

    client = CopilotClient(
        endpoint=endpoint,
        api_key=api_key,
        model=model
    )

    reasoner = CopilotReasoner(client)

    goal = Goal(name="deploy_cluster", description="Deploy a new cluster.")

    execution_history = [
        ExecutionRecord(
            observation=ToolResult(
                success=True,
                exit_code=0,
                data={
                    "cluster_state": "not_deployed"
                }
            ),
            decision=Decision(
                tool="deploy_cluster",
                reason="Cluster missing"
            ),
            result=ToolResult(
                success=True,
                exit_code=0
            )
        )
    ]
    observation = ToolResult(
        success=True,
        exit_code=0,
        data={
            "cluster_state": "failed"
        }
    )
    tools = [
        ToolDefinition(name="deploy_cluster", description="Deploys a new cluster. Called ONLY when cluster_state is not_deployed."),
        ToolDefinition(name="scale_cluster", description="Scales the existing cluster. Called ONLY when scaling is the goal."),
        ToolDefinition(name="monitor_cluster", description="Monitors the cluster health. Called ONLY when cluster_state is deploying."),
        ToolDefinition(name="investigate_failure", description="Investigates failures. Called ONLY when cluster_state is failed."),
        ToolDefinition(name="done", description="Goal is satisfied. Called when the current observation shows the goal is already achieved."),
    ]

    try:
        decision = reasoner.decide(
            goal,
            observation,
            execution_history,
            tools
        )
        print(decision)
    except Exception as exc:
        print(f"Copilot call failed: {exc}")
        print("Make sure your Azure OpenAI endpoint and API key are configured.")
