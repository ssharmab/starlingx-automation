# SPDX-License-Identifier: Apache-2.0
# llm/ollama_client.py

from ollama import Client

from client.base_llm_client import BaseLLMClient


class OllamaClient(
    BaseLLMClient
):

    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434"
    ):
        self._model = model
        self._client = Client(
            host=host
        )

    def generate(
        self,
        prompt: str
    ) -> str:

        response = self._client.chat(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return response["message"]["content"]