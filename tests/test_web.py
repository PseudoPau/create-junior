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
