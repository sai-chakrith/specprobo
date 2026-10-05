import os
from typing import Any

import requests
import streamlit as st


def _request(method: str, path: str, **kwargs: Any) -> requests.Response:
    base = st.session_state.get("api_url", "http://127.0.0.1:8000").rstrip("/")
    headers = {"X-API-Key": st.session_state.get("api_key", "")}
    return requests.request(method, f"{base}{path}", headers=headers, timeout=30, **kwargs)


st.set_page_config(page_title="SpecProbe review", layout="wide")
st.title("SpecProbe review")
st.session_state.setdefault("api_url", os.environ.get("SPECPROBE_API_URL", "http://127.0.0.1:8000"))
st.session_state["api_url"] = st.sidebar.text_input("API URL", st.session_state["api_url"])
st.session_state["api_key"] = st.sidebar.text_input("Workspace API key", type="password")
workspace_id = st.sidebar.text_input("Workspace")

if workspace_id and st.session_state.get("api_key"):
    st.subheader("Proposed fields")
    response = _request("GET", f"/workspaces/{workspace_id}/fields")
    if response.ok:
        fields = response.json()
        for field in fields:
            columns = st.columns([3, 3, 1, 1, 1])
            columns[0].write(field["json_path"])
            columns[1].write(field["value"])
            columns[2].write(field["status"])
            decision = columns[3].selectbox(
                "Decision",
                ["approved", "edited", "rejected"],
                key=f"decision-{field['id']}",
                label_visibility="collapsed",
            )
            if columns[4].button("Review", key=f"review-{field['id']}"):
                review = _request(
                    "POST",
                    f"/workspaces/{workspace_id}/fields/{field['id']}/review",
                    json={"decision": decision},
                )
                st.toast(review.json() if review.ok else review.text)
    else:
        st.error(response.text)

    upload = st.file_uploader("Upload PDF or XLSX", type=["pdf", "xlsx"])
    if upload is not None and st.button("Ingest document"):
        result = _request(
            "POST",
            f"/workspaces/{workspace_id}/documents",
            files={"file": (upload.name, upload.getvalue(), upload.type)},
        )
        st.toast(result.json() if result.ok else result.text)

    suite_id = st.text_input("Suite id", value="review-suite")
    if st.button("Generate approved suite"):
        result = _request("POST", f"/workspaces/{workspace_id}/suites/{suite_id}")
        st.json(result.json() if result.ok else {"error": result.text})
    run_id = st.text_input("Run id", value="review-run")
    if st.button("Run clean and mutants"):
        result = _request(
            "POST",
            f"/workspaces/{workspace_id}/runs/{run_id}",
            params={"suite_id": suite_id, "mutants": True},
        )
        if result.ok:
            report = result.json()
            st.metric("Passed", f"{report.get('passed', 0)}/{report.get('total', 0)}")
            st.json(report)
        else:
            st.error(result.text)