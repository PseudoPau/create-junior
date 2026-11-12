from fastapi.testclient import TestClient

from app.main import app


def test_workshop_shell_and_static_assets_are_served():
    client = TestClient(app)

    page = client.get("/")
    css = client.get("/static/web.css")
    js = client.get("/static/app.js")

    assert page.status_code == 200
    assert "Create <span>Junior</span>" in page.text
    assert "/static/app.js" in page.text
    assert css.status_code == 200 and "--accent" in css.text
    assert js.status_code == 200 and "api/projects" in js.text
