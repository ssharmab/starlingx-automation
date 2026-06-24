# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod

class BaseLLMClient(ABC):
    """
    Base class for LLM clients. This class defines the interface that all LLM clients
    must implement.
    """

    @abstractmethod
    def generate(self, 
                 prompt: str
    ) -> str:
        """
        Generate a response from the LLM based on the provided prompt.

        Args:
            prompt (str): The input prompt to send to the LLM.
        """

        