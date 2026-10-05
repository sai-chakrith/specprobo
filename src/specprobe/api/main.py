from fastapi import FastAPI, Header, HTTPException

from ..storage.audit import WorkspaceRepository

app = FastAPI(title="SpecProbe")
repository = WorkspaceRepository()


def require_workspace(workspace_id: str, x_workspace_key: str | None) -> None:
    if not x_workspace_key or x_workspace_key != workspace_id:
        raise HTTPException(status_code=403, detail="workspace access denied")


@app.post("/workspaces/{workspace_id}")
def create_workspace(workspace_id: str, x_workspace_key: str | None = Header(default=None)) -> dict[str, str]:
    require_workspace(workspace_id, x_workspace_key)
    repository.put(workspace_id, "workspace", {"workspace_id": workspace_id})
    return {"workspace_id": workspace_id}


@app.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, x_workspace_key: str | None = Header(default=None)) -> dict[str, object]:
    require_workspace(workspace_id, x_workspace_key)
    return {"workspace_id": workspace_id, "rows": repository.list(workspace_id)}
