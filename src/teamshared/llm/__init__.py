"""LLM helpers shared by distiller, curator, agent runner, and tools."""

from teamshared.llm.completion import create_chat_completion

__all__ = ["create_chat_completion"]
