from fastapi.testclient import TestClient

from app.main import app


def test_workshop_shell_and_static_assets_are_served():
    client = TestClient(app)

    page = client.get("/")
    css = client.get("/static/studio.css")
    js = client.get("/static/studio.js")

    assert page.status_code == 200
    assert all(f'id="{view}"' in page.text for view in (
        "studio", "stage-nav", "step-body", "step-actions", "viewport", "drawing-view"
    ))
    assert 'type="module" src="/static/studio.js' in page.text
    assert 'src="/static/app.js' not in page.text
    assert 'role="alert"' in page.text
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert js.status_code == 200 and "api/workbench" in js.text


def test_editor_shell_and_assets_are_served():
    client = TestClient(app)

    page = client.get("/editor")
    css = client.get("/static/editor.css")
    js = client.get("/static/editor.js")

    assert page.status_code == 200
    assert all(f'id="{element}"' in page.text for element in (
        "editor", "tree", "viewport", "right-body", "toolbar", "empty"
    ))
    assert 'type="module" src="/static/editor.js' in page.text
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert js.status_code == 200 and "WorkshopViewport" in js.text and "api/workbench" in js.text
    assert 'class="mode-switch"' in client.get("/").text
