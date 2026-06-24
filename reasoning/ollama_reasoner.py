# reasoning/ollama_reasoner.py

import json

from reasoning.llm_reasoner_base import BaseLLMReasoner

from client.base_llm_client import BaseLLMClient

from agent.structs.goal import Goal
from agent.structs.decision import Decision
from agent.structs.execution_record import ExecutionRecord
from agent.structs.tool_definition import ToolDefinition

from common.tool_result import ToolResult


class OllamaReasoner(
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
You are a cluster deployment agent.

Goal:
{goal.description}

Current Observation:
{observation.data}

Execution History:
{execution_history}

Available Tools:
{tools}

Choose the next tool.

Return JSON only:

{{
  "tool": "...",
  "reason": "...",
  "parameters": {{}}
}}
"""
    
if __name__ == "__main__":
    # Example usage
    from client.ollama_client import OllamaClient

    model_name = "llama3.2"
    client = OllamaClient(
        model=model_name,
        host="http://localhost:11434"
    )

    reasoner = OllamaReasoner(client)

    goal = Goal(name="deploy_cluster", description="Deploy a new cluster.")
    observation = ToolResult(
        success=True,
        exit_code=0,
        data={"cluster_state": "not_deployed"}
    )
    execution_history = []
    tools = [
        ToolDefinition(name="deploy_cluster", description="Deploys a new cluster."),
        ToolDefinition(name="scale_cluster", description="Scales the existing cluster."),
        ToolDefinition(name="monitor_cluster", description="Monitors the cluster health.")
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
        print(f"Ollama call failed: {exc}")
        print("Make sure Ollama is running and the model is installed.")
        print(f"Try: ollama serve && ollama pull {model_name}")