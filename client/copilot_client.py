# SPDX-License-Identifier: Apache-2.0

from openai import AzureOpenAI

from client.base_llm_client import BaseLLMClient


class CopilotClient(BaseLLMClient):

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str = "gpt-4",
        api_version: str = "2024-02-15-preview"
    ):
        self._model = model
        self._client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version
        )

    def generate(
        self,
        prompt: str
    ) -> str:

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return response.choices[0].message.content
