from .audit import collection_name


class VectorStore:
    """Small Chroma-compatible boundary; the in-memory backend keeps tests offline."""

    def __init__(self) -> None:
        self._collections: dict[str, list[dict[str, object]]] = {}

    def add(self, workspace_id: str, kind: str, document: dict[str, object]) -> None:
        self._collections.setdefault(collection_name(workspace_id, kind), []).append(dict(document))

    def list(self, workspace_id: str, kind: str) -> list[dict[str, object]]:
        return [dict(item) for item in self._collections.get(collection_name(workspace_id, kind), [])]
