

from llm_reasoner_base import LLMReasonerBase

class ChatGPTReasoner(LLMReasonerBase):
    """
    A simple implementation of an LLM-based reasoner that uses the OpenAI ChatGPT API to make decisions.
    This is a very basic implementation and can be extended with more sophisticated prompting, error handling, etc.
    
    Example usage:
        reasoner = ChatGPTReasoner()
        decision = reasoner.decide(
            goal=current_goal,
            registry=tool_registry,
            state=current_state,
            correlation_id=correlation_id,
        )
    """