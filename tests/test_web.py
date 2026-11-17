from fastapi.testclient import TestClient

from app.main import app


def test_workshop_shell_and_static_assets_are_served():
    client = TestClient(app)

    page = client.get("/")
    css = client.get("/static/web.css")
    js = client.get("/static/app.js")

    assert page.status_code == 200
    assert "开始制作" in page.text and "三维工作台" in page.text
    assert all(f'id="{view}"' in page.text for view in ("home-page", "design-page", "package-page"))
    assert "/static/app.js" in page.text
    assert css.status_code == 200 and "--accent" in css.text
    assert js.status_code == 200 and "api/workbench" in js.text
