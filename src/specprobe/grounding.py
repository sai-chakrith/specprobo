"""Conservative extractive support gate; not a semantic entailment model."""

import re
from typing import Any


def normalize(text: str) -> str:
    return " ".join(text.casefold().split()).strip(' ."')


def supported_answer(answer: str, evidence: list[dict[str, Any]]) -> bool:
    """Every nonempty claim must quote a contiguous span of its cited evidence.

    This intentionally rejects unsupported paraphrases and correct citation numbers
    attached to invented claims. Semantic groundedness still needs human assessment.
    """
    claims = [line.strip() for line in answer.splitlines() if line.strip()]
    if not claims:
        return False
    for claim in claims:
        ids = [int(n) for n in re.findall(r"\[(\d+)\]", claim)]
        text = normalize(re.sub(r"\[\d+\]", "", claim))
        if not text or not ids or any(n < 1 or n > len(evidence) for n in ids):
            return False
        if not any(text in normalize(str(evidence[n - 1]["text"])) for n in ids):
            return False
        if re.search(r"ignore .*instructions|system prompt|reveal .*secret", text):
            return False
    return True


def conflicting_evidence(evidence: list[dict[str, Any]]) -> bool:
    values: dict[str, str] = {}
    for item in evidence:
        text = str(item["text"])
        match = re.match(
            r"((?:dids|routines|services|sessions|security_levels)\[\d+\]\.\w+):\s*(.+)$", text
        )
        if match:
            key, value = match.groups()
            if key in values and normalize(values[key]) != normalize(value):
                return True
            values[key] = value
    return False
