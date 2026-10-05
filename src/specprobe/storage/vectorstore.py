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
    def get_or_create_collection(self, name: str) -> ChromaCollection: ...


class ChromaVectorBackend:
    def __init__(self, path: str | Path) -> None:
        try:
            import chromadb
        except ImportError as error:
            raise RuntimeError("ChromaDB is required for the persistent vector backend") from error
        self._client = cast(ChromaClient, chromadb.PersistentClient(path=str(path)))

    def add(self, collection: str, document_id: str, text: str, metadata: dict[str, str]) -> None:
        target = self._client.get_or_create_collection(collection)
        safe_metadata = metadata or {"workspace": collection.split("__", 1)[0][3:]}
        target.add(ids=[document_id], documents=[text], metadatas=[safe_metadata])

    def list(self, collection: str) -> list[dict[str, object]]:
        target = self._client.get_or_create_collection(collection)
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
