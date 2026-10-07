"""Run configured embedding/model benchmarks; never replace them with demo models."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from specprobe.grounding import conflicting_evidence, supported_answer
from specprobe.ingest.llm import OllamaClient
from specprobe.storage.vectorstore import LocalEmbedding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("data/evaluation/ai_corpus.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = os.environ.get("SPECPROBE_OLLAMA_MODEL")
    model_path = os.environ.get("SPECPROBE_EMBED_MODEL_PATH")
    endpoint = os.environ.get("SPECPROBE_OLLAMA_URL")
    report = {
        "corpus_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
        "model": model,
        "embedding_path": model_path,
        "human_semantic_groundedness": None,
    }
    if not all((model, model_path, endpoint)):
        report.update(
            status="NOT_RUN",
            dependency=(
                "Set SPECPROBE_OLLAMA_URL, SPECPROBE_OLLAMA_MODEL and "
                "SPECPROBE_EMBED_MODEL_PATH to available local infrastructure."
            ),
        )
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        return 2
    embedding = LocalEmbedding(model_path)
    corpus = json.loads(args.corpus.read_text())
    rows = corpus["documents"]
    vectors = embedding([r["text"] for r in rows])
    results = []
    for query in corpus["queries"]:
        start = time.perf_counter()
        q = embedding([query["question"]])[0]
        ranked = sorted(
            zip(rows, vectors, strict=True),
            key=lambda rv: sum(a * b for a, b in zip(q, rv[1], strict=True)),
            reverse=True,
        )
        top = [r for r, _ in ranked[:5]]
        relevant = set(query["relevant_ids"])
        retrieved = [r["id"] for r in top]
        ranks = [i + 1 for i, r in enumerate(retrieved) if r in relevant]
        evidence = [{**r, "citation": i + 1} for i, r in enumerate(top)]
        answer = OllamaClient(model=model).answer(query["question"], evidence)
        results.append(
            {
                "id": query["id"],
                "recall_at_5": len(relevant & set(retrieved)) / len(relevant) if relevant else None,
                "reciprocal_rank": 1 / min(ranks) if ranks else 0,
                "extractive_support": supported_answer(answer, evidence),
                "conflict_detected": conflicting_evidence(evidence),
                "expected_behavior": query["expected_behavior"],
                "answer": answer,
                "evidence": evidence,
                "latency_seconds": time.perf_counter() - start,
                "human_semantic_review": "pending",
            }
        )
    report.update(
        status="MEASURED_CONFIGURED_LOCAL_MODELS",
        results=results,
        limitations=(
            "Extraction support is a conservative string gate, not semantic correctness. "
            "Review insufficient-evidence, contradictory-source and injection cases manually."
        ),
    )
    args.output.write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
