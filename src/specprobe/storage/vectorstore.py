import hashlib
import math
import os
from pathlib import Path
from typing import Protocol, cast

KINDS = frozenset({"standard", "oem", "ecu", "project"})


def collection_name(workspace_id: str, kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unsupported vector collection kind: {kind}")
    return f"ws_{workspace_id}__{kind}"


class VectorBackend(Protocol):
    def add(
        self, collection: str, document_id: str, text: str, metadata: dict[str, str]
    ) -> None: ...

    def list(self, collection: str) -> list[dict[str, object]]: ...


class InMemoryVectorBackend:
    def __init__(self) -> None:
        self._rows: dict[str, list[dict[str, object]]] = {}

    def add(self, collection: str, document_id: str, text: str, metadata: dict[str, str]) -> None:
        self._rows.setdefault(collection, []).append(
            {"id": document_id, "text": text, "metadata": dict(metadata)}
        )

    def list(self, collection: str) -> list[dict[str, object]]:
        return [dict(row) for row in self._rows.get(collection, [])]


class ChromaCollection(Protocol):
    def add(
        self, ids: list[str], documents: list[str], metadatas: list[dict[str, str]]
    ) -> None: ...

    def get(self) -> dict[str, object]: ...


class ChromaClient(Protocol):
    def get_or_create_collection(
        self, name: str, embedding_function: object
    ) -> ChromaCollection: ...


class HashEmbedding:
    """Small deterministic embedding that never reaches the network."""

    def __init__(self, dimension: int = 32) -> None:
        self.dimension = dimension

    def __call__(self, input: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in input:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            values = [digest[index % len(digest)] / 255.0 for index in range(self.dimension)]
            norm = math.sqrt(sum(value * value for value in values)) or 1.0
            vectors.append([value / norm for value in values])
        return vectors

    def embed_query(self, input: str) -> list[float]:
        return self([input])[0]

    def name(self) -> str:
        return "specprobe-hash"

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> set[str]:
        return {"cosine"}


class LocalEmbedding:
    def __init__(self, model_path: str | Path | None = None) -> None:
        path = Path(model_path or os.environ.get("SPECPROBE_EMBED_MODEL_PATH", ""))
        if not path.is_dir():
            raise RuntimeError(
                "SPECPROBE_EMBED_MODEL_PATH must point to a locally downloaded "
                "BGE-small or E5-small model directory"
            )
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "LocalEmbedding requires sentence-transformers; install it for local model use"
            ) from error
        self._model = SentenceTransformer(str(path), local_files_only=True)

    def __call__(self, input: list[str]) -> list[list[float]]:
        return cast(list[list[float]], self._model.encode(input, convert_to_numpy=False).tolist())

    def embed_query(self, input: str) -> list[float]:
        return self([input])[0]

    def name(self) -> str:
        return "specprobe-local"

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> set[str]:
        return {"cosine"}


class ChromaVectorBackend:
    def __init__(self, path: str | Path, embedding_function: object) -> None:
        try:
            import chromadb
        except ImportError as error:
            raise RuntimeError("ChromaDB is required for the persistent vector backend") from error
        settings = chromadb.config.Settings(anonymized_telemetry=False)
        self._embedding_function = embedding_function
        self._client = cast(
            ChromaClient, chromadb.PersistentClient(path=str(path), settings=settings)
        )

    def add(self, collection: str, document_id: str, text: str, metadata: dict[str, str]) -> None:
        target = self._client.get_or_create_collection(
            collection, embedding_function=self._embedding_function
        )
        safe_metadata = metadata or {"workspace": collection.split("__", 1)[0][3:]}
        target.add(ids=[document_id], documents=[text], metadatas=[safe_metadata])

    def list(self, collection: str) -> list[dict[str, object]]:
        target = self._client.get_or_create_collection(
            collection, embedding_function=self._embedding_function
        )
        data = target.get()
        ids = cast(list[str], data.get("ids", []))
        documents = cast(list[str], data.get("documents", []))
        metadatas = cast(list[dict[str, object]], data.get("metadatas", []))
        return [
            {"id": identifier, "text": documents[index], "metadata": metadatas[index]}
            for index, identifier in enumerate(ids)
        ]


class ScopedVectorStore:
    def __init__(self, backend: VectorBackend, workspace_id: str) -> None:
        self._backend = backend
        self.workspace_id = workspace_id

    def add(self, kind: str, document_id: str, text: str, metadata: dict[str, str]) -> None:
        self._backend.add(collection_name(self.workspace_id, kind), document_id, text, metadata)

    def list(self, kind: str) -> list[dict[str, object]]:
        return self._backend.list(collection_name(self.workspace_id, kind))


def scoped_store(backend: VectorBackend, workspace_id: str) -> ScopedVectorStore:
    return ScopedVectorStore(backend, workspace_id)
