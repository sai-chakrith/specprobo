import json
import os
import re
from typing import Any, Literal, Protocol
from urllib.request import Request, urlopen

from pydantic import BaseModel

from ..domain.schema import Precondition


class ConditionResult(BaseModel):
    target: str
    condition: Precondition


class LLMClient(Protocol):
    def parse_condition(self, text: str) -> ConditionResult | None: ...

    def normalize(self, name: str, value: Any) -> Any: ...


class FakeLLM:
    def parse_condition(self, text: str) -> ConditionResult | None:
        if " and " in text.lower():
            return None
        target_match = re.search(r"(DID|routine)\s+(0x[0-9A-Fa-f]+)", text, re.IGNORECASE)
        if target_match is None:
            return None
        signal_matches = re.findall(
            r"(?:when|while|requires)\s+([A-Za-z_][A-Za-z0-9_]*)", text
        )
        if not signal_matches:
            return None
        signal = signal_matches[-1]
        op: Literal["==", "!=", "<", "<=", ">", ">="]
        value_match = re.search(
            r"(?:below|under|less than)\s+(-?\d+(?:\.\d+)?)\s*([A-Za-z/°]+)?",
            text,
            re.IGNORECASE,
        )
        if value_match:
            value: int | float = float(value_match.group(1))
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            op = "<"
            unit = value_match.group(2)
        elif re.search(r"false|off|not", text, re.IGNORECASE):
            value = False
            op = "!="
            unit = None
        else:
            value = True
            op = "=="
            unit = None
        condition = Precondition(
            kind="signal",
            signal=signal,
            op=op,
            value=value,
            unit=unit,
            source_text=text,
        )
        return ConditionResult(target=target_match.group(2).lower(), condition=condition)

    def normalize(self, name: str, value: Any) -> Any:
        return value


class OllamaClient:
    def __init__(
        self, model: str = "llama3.2", endpoint: str | None = None, retries: int = 2
    ) -> None:
        self.model = model
        self.endpoint = endpoint or os.environ.get("SPECPROBE_OLLAMA_URL", "")
        self.retries = retries

    def parse_condition(self, text: str) -> ConditionResult | None:
        if not self.endpoint:
            raise RuntimeError("Ollama is opt-in; set SPECPROBE_OLLAMA_URL to enable it")
        schema = ConditionResult.model_json_schema()
        payload = {"model": self.model, "format": schema, "stream": False, "prompt": text}
        for _ in range(self.retries + 1):
            request = Request(
                self.endpoint.rstrip("/") + "/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request, timeout=30) as response:
                raw = json.loads(response.read().decode("utf-8"))
            try:
                result = json.loads(str(raw["response"]))
                return ConditionResult.model_validate(result)
            except (KeyError, TypeError, ValueError):
                continue
        raise RuntimeError("Ollama returned invalid condition JSON after retries")

    def normalize(self, name: str, value: Any) -> Any:
        raise RuntimeError("Ollama is opt-in and unavailable in offline mode")
