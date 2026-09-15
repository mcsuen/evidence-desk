"""Structured output helpers and completion through the task-bound local Agent."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

class LLMUnavailable(RuntimeError):
    pass

@dataclass
class LLMResult:
    data: dict[str, Any]
    provider: str
    model: str
    raw: str

def strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a JSON schema acceptable to strict structured-output modes: additionalProperties=false, all required."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            node = dict(node)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
                node["properties"] = {k: walk(v) for k, v in node["properties"].items()}
            for key in ("items",):
                if key in node:
                    node[key] = walk(node[key])
            for key in ("anyOf", "oneOf", "allOf"):
                if key in node:
                    node[key] = [walk(x) for x in node[key]]
            if "$defs" in node:
                node["$defs"] = {k: walk(v) for k, v in node["$defs"].items()}
            node.pop("default", None)
            node.pop("title", None)
            return node
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


def complete_json(prompt, schema, system=None, provider=None, model=None, timeout=600, max_output_tokens=8000):
    from pitr.agent_runtime import current
    scope=current.get()
    if not scope:
        raise LLMUnavailable('请求尚未绑定本机 Agent')
    runtime,task,fence=scope
    return runtime.complete_json(task,prompt,schema,system=system,timeout=timeout,fence=fence)
