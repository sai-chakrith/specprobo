from pathlib import Path
from unittest.mock import patch

import requests
from streamlit.testing.v1 import AppTest

UI = Path(__file__).parents[1] / "src/specprobe/ui/app.py"


def test_ui_onboarding_and_authenticated_empty_workspace():
    app = AppTest.from_file(str(UI), default_timeout=20).run()
    assert not app.exception
    assert "Enter a workspace" in app.info[0].value
    response = requests.Response()
    response.status_code = 200
    response._content = b"[]"
    with patch("requests.request", return_value=response):
        for widget in app.sidebar.text_input:
            if widget.label == "Workspace":
                widget.set_value("one")
            elif widget.label == "Workspace API key":
                widget.set_value("key-one1")
            elif widget.label == "Reviewer name":
                widget.set_value("engineer")
        app.run()
        assert not app.exception
        assert [tab.label for tab in app.tabs] == [
            "Knowledge",
            "Specification review",
            "Tests",
            "Reports",
        ]
        generate = next(
            button
            for button in app.button
            if button.label == "Generate suite from selected document"
        )
        assert generate.disabled
        saved_id = app.session_state["new_suite_id"]
        app.run()
        assert app.session_state["new_suite_id"] == saved_id
        assert not app.exception
