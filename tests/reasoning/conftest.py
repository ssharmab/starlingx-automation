# SPDX-License-Identifier: Apache-2.0
"""
conftest.py for reasoning tests.

Patches broken import paths in the project source so tests can run.

Known issues in the codebase:
  - agent/structs/__init__.py uses bare `from decision import Decision`
  - reasoning/ollama_reasoner.py uses `from llm_reasoner_base import LLMReasonerBase`
    and then `class OllamaReasoner(BaseLLMReasoner):`
  - reasoning/llm_reasoner_base.py does `from tools.tool_definition import ToolDefinition`
    but the file is actually at agent/structs/tool_definition.py
  - tools/base.py does `from agent.structs.tool_definition import ToolDefinition`
    which triggers agent/structs/__init__.py
"""
import sys
from pathlib import Path
from types import ModuleType

# Ensure the project root is on sys.path
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Add agent/structs to sys.path so bare imports (decision, goal, etc.) resolve
_STRUCTS_DIR = str(Path(_PROJECT_ROOT) / "agent" / "structs")
if _STRUCTS_DIR not in sys.path:
    sys.path.insert(0, _STRUCTS_DIR)

# Pre-import struct modules with bare names so agent/structs/__init__.py works
import decision  # noqa: F401
import goal      # noqa: F401
import execution_record  # noqa: F401
import tool_definition   # noqa: F401

# Create a fake `tools.tool_definition` module pointing to the real one
# (reasoning/llm_reasoner_base.py expects `from tools.tool_definition import ToolDefinition`)
import agent.structs.tool_definition as _real_td

_fake_tools_td = ModuleType("tools.tool_definition")
_fake_tools_td.ToolDefinition = _real_td.ToolDefinition
sys.modules.setdefault("tools.tool_definition", _fake_tools_td)

# Also ensure `tools` package is importable (its __init__.py is just a license header)
# We need `tools` in sys.modules as a package before tools.tool_definition
if "tools" not in sys.modules:
    import tools  # noqa: F401 — import the real package

# Now fix the llm_reasoner_base bare module import used by ollama_reasoner.py
from reasoning.llm_reasoner_base import BaseLLMReasoner

_fake_llm_module = ModuleType("llm_reasoner_base")
_fake_llm_module.LLMReasonerBase = BaseLLMReasoner
_fake_llm_module.BaseLLMReasoner = BaseLLMReasoner
sys.modules.setdefault("llm_reasoner_base", _fake_llm_module)
