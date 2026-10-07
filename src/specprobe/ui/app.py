import json
import os
from typing import Any
from uuid import uuid4

import requests
import streamlit as st


def request(method: str, path: str, **kwargs: Any) -> requests.Response | None:
    try:
        response = requests.request(
            method,
            st.session_state["api_url"].rstrip("/") + path,
            headers={"X-API-Key": st.session_state.get("api_key", "")},
            timeout=180,
            **kwargs,
        )
        if not response.ok:
            st.error(response.text)
            return None
        return response
    except requests.RequestException as error:
        st.error(f"Cannot reach the API: {error}")
        return None


st.set_page_config(page_title="SpecProbe", layout="wide")
st.title("SpecProbe diagnostics assistant")
st.caption("Review specifications, generate diagnostic tests, and validate against the simulator.")
st.session_state["api_url"] = st.sidebar.text_input(
    "API URL", os.environ.get("SPECPROBE_API_URL", "http://127.0.0.1:8000")
)
st.session_state["api_key"] = st.sidebar.text_input("Workspace API key", type="password")
workspace = st.sidebar.text_input("Workspace")
reviewer = st.sidebar.text_input("Reviewer name")
if st.sidebar.button("Create workspace") and workspace:
    response = request(
        "POST",
        "/workspaces",
        json={"workspace_id": workspace, "api_key": st.session_state["api_key"]},
    )
    if response is not None:
        st.sidebar.success("Workspace created")
if not workspace or not st.session_state["api_key"]:
    st.info(
        "Enter a workspace and API key in the sidebar. New keys need at least eight characters."
    )
    st.stop()
base = f"/workspaces/{workspace}"
knowledge, review, suites, reports = st.tabs(
    ["Knowledge", "Specification review", "Tests", "Reports"]
)
with knowledge:
    kind = st.selectbox("Knowledge collection", ["oem", "standard", "ecu", "project"])
    upload = st.file_uploader(
        "Upload an authorized specification or reference", type=["pdf", "xlsx", "json", "txt", "md"]
    )
    if st.button("Ingest") and upload:
        response = request(
            "POST",
            base + "/documents",
            params={"kind": kind},
            files={"file": (upload.name, upload.getvalue(), upload.type)},
        )
        if response is not None:
            st.success(
                "Document ingested. Review the source and extracted fields before generating tests."
            )
    document_response = request("GET", base + "/documents")
    documents = document_response.json() if document_response is not None else []
    for doc in documents:
        with st.expander(
            f"{doc['name']} — {'approved' if doc['approved'] else 'awaiting approval'}"
        ):
            st.write(doc["id"], doc["kind"])
            approve, revoke = st.columns(2)
            for column, label, approved in [
                (approve, "Approve source", True),
                (revoke, "Revoke source", False),
            ]:
                if column.button(label, key=f"{label}-{doc['id']}", disabled=not reviewer):
                    if (
                        request(
                            "POST",
                            base + f"/documents/{doc['id']}/review",
                            json={"approved": approved, "reviewer": reviewer},
                        )
                        is not None
                    ):
                        st.rerun()
    question = st.text_input("Diagnostic question")
    use_llm = st.checkbox("Use the configured local model to explain retrieved evidence")
    if st.button("Search approved knowledge") and question:
        response = request(
            "POST", base + "/query", json={"question": question, "kind": kind, "use_llm": use_llm}
        )
        if response is not None:
            answer = response.json()
            st.write(answer["answer"])
            for citation in answer["citations"]:
                with st.expander(f"[{citation['citation']}] {citation['name']}"):
                    st.json(citation)
            st.caption(answer["limitation"])
with review:
    response = request("GET", base + "/fields")
    fields = response.json() if response is not None else []
    selected_doc = st.selectbox(
        "Source document",
        [d["id"] for d in documents],
        format_func=lambda value: next(d["name"] for d in documents if d["id"] == value),
    )
    selected_fields = [f for f in fields if f["document_id"] == selected_doc]
    reviewed_all = st.checkbox("I have reviewed every extracted field in this document")
    if st.button(
        "Approve all reviewed fields",
        disabled=not reviewer or not reviewed_all or not selected_fields,
    ):
        if (
            request(
                "POST",
                base + "/fields/review-batch",
                json={"reviewer": reviewer, "field_ids": [f["id"] for f in selected_fields]},
            )
            is not None
        ):
            st.rerun()
    for field in selected_fields:
        with st.expander(f"{field['json_path']} — {field['status']}"):
            st.json(field["value"])
            st.caption("Source evidence")
            st.json(field["provenance"])
            decision = st.selectbox("Decision", ["approved", "edited", "rejected"], key=field["id"])
            edited = st.text_area(
                "Replacement value (JSON)", json.dumps(field["value"]), key="edit-" + field["id"]
            )
            if st.button("Save decision", key="save-" + field["id"], disabled=not reviewer):
                try:
                    value = {"value": json.loads(edited)} if decision == "edited" else None
                    if (
                        request(
                            "POST",
                            base + f"/fields/{field['id']}/review",
                            json={"decision": decision, "value": value, "reviewer": reviewer},
                        )
                        is not None
                    ):
                        st.rerun()
                except json.JSONDecodeError:
                    st.error("Replacement value must be valid JSON.")
with suites:
    st.caption("Approve every extracted field. Missing or rejected fields block generation.")
    st.session_state.setdefault("new_suite_id", "suite-" + str(uuid4())[:8])
    suite_id = st.text_input("Suite ID", key="new_suite_id")
    if st.button("Generate suite from selected document", disabled=not selected_doc):
        response = request(
            "POST", base + f"/suites/{suite_id}", params={"document_id": selected_doc}
        )
        if response is not None:
            st.session_state["active_suite"] = suite_id
            st.json(response.json())
    active_suite = st.text_input("Suite to inspect", st.session_state.get("active_suite", ""))
    if active_suite:
        response = request("GET", base + f"/suites/{active_suite}")
        if response is not None:
            payload = response.json()
            st.metric("Generated cases", payload["case_count"])
            st.json(payload["coverage"])
            st.dataframe(
                [
                    {
                        "id": c["id"],
                        "request": " / ".join(c["steps"]),
                        "expected": c["expected"],
                        "tags": ", ".join(c["tags"]),
                    }
                    for c in payload["cases"]
                ],
                use_container_width=True,
            )
            with st.expander("Specification and full test snapshot"):
                st.json(payload)
            if st.button("Approve reviewed suite", disabled=not reviewer):
                if (
                    request(
                        "POST",
                        base + f"/suites/{active_suite}/review",
                        json={"approved": True, "reviewer": reviewer},
                    )
                    is not None
                ):
                    st.rerun()
            if st.button("Revoke suite approval", disabled=not reviewer):
                if (
                    request(
                        "POST",
                        base + f"/suites/{active_suite}/review",
                        json={"approved": False, "reviewer": reviewer},
                    )
                    is not None
                ):
                    st.rerun()
            if payload["approved"]:
                if st.button("Prepare automation downloads"):
                    for format, extension in [("python", "py"), ("json", "json")]:
                        export = request(
                            "GET",
                            base + f"/suites/{active_suite}/export",
                            params={"format": format},
                        )
                        if export is not None:
                            st.download_button(
                                f"Download {format}",
                                export.content,
                                f"specprobe_suite.{extension}",
                                key=format,
                            )
                mutants = st.checkbox("Include mutation evaluation (may take several minutes)")
                if st.button("Run approved suite on simulator"):
                    run_id = "run-" + str(uuid4())
                    response = request(
                        "POST",
                        base + f"/runs/{run_id}",
                        params={"suite_id": active_suite, "mutants": mutants},
                    )
                    if response is not None:
                        st.session_state["last_report"] = response.json()
                        st.success("Run saved: " + run_id)
            with st.expander("Validate a request and compare a response"):
                message = st.text_input("Request hex", "1001")
                actual = st.text_input("Actual response hex (optional)")
                setup = st.text_input("Setup requests, comma separated", "")
                environment = st.text_area("Environment signals (JSON)", "{}")
                if st.button("Validate message"):
                    try:
                        response = request(
                            "POST",
                            base + f"/suites/{active_suite}/validate-message",
                            json={
                                "request_hex": message,
                                "actual_hex": actual or None,
                                "setup_hex": [x.strip() for x in setup.split(",") if x.strip()],
                                "environment": json.loads(environment),
                            },
                        )
                        if response is not None:
                            st.json(response.json())
                    except json.JSONDecodeError:
                        st.error("Environment must be valid JSON.")
with reports:
    run_id = st.text_input("Saved run ID")
    if st.button("Load saved report") and run_id:
        response = request("GET", base + f"/runs/{run_id}")
        if response is not None:
            st.session_state["last_report"] = response.json()
    report = st.session_state.get("last_report")
    if report:
        st.metric("Passed", f"{report['passed']}/{report['total']}")
        st.json(report["coverage"])
        st.dataframe(report["results"])
        st.download_button("Download report", json.dumps(report, indent=2), "report.json")
    if st.button("View audit history"):
        response = request("GET", base + "/audit")
        if response is not None:
            st.json(response.json())
