"""Task-level interaction smoke test for the chair-scope editor.

Run against a live local server:
    .venv/bin/python scripts/verify_interaction.py

It uses two projects on purpose:
- CAFE CHAIR exercises the editable path (size/undo/drag/hole/check/cut).
- PS 2026 is a reference reconstruction and also exercises the honest refusal
  when a dimension has no verified association, plus docs/package/delivery.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def post(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else b""
    headers = {"content-type": "application/json"} if body is not None else {}
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def create_cafe() -> str:
    demo = post("/api/workbench/demos/cafe-chair")
    project = demo["project"]
    post(f"/api/workbench/projects/{project['id']}/proposal/accept",
         {"expected_revision": project["revision"], "proposal_id": demo["proposal"]["id"], "accept_connections": False})
    return project["id"]


def create_ps() -> str:
    return post("/api/workbench/demos/ps2026")["id"]


def main() -> int:
    from playwright.sync_api import sync_playwright

    cafe_id = create_cafe()
    ps_id = create_ps()
    errors: list[str] = []
    checks = 0

    def expect(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(message)
        print(f"  ok {checks:02d}  {message}")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))

            def open_project(project_id: str) -> None:
                page.goto(f"{BASE}/editor?project={project_id}", wait_until="networkidle")
                page.wait_for_selector("#viewport canvas")
                time.sleep(1.5)

            def revision() -> str:
                return page.inner_text("#project-meta").split("·")[0].strip()

            def size_inputs():
                return page.locator("#right-body .section").filter(has_text="尺寸").locator("input")

            # ---- CAFE: editable happy path -------------------------------------
            open_project(cafe_id)
            expect(page.title().startswith("Junior"), "编辑器页能打开")
            expect(page.locator("#tree .row").count() >= 11, "对象树有零件和连接")
            start = revision()
            page.locator("#tree .row").filter(has_text="座板").first.click(); time.sleep(0.4)
            expect(page.inner_text("#right-title") == "属性", "选中座板出现属性面板")
            expect(size_inputs().count() == 3, "尺寸有长/宽/厚三个输入")

            size_inputs().nth(1).fill(str(float(size_inputs().nth(1).input_value()) + 2))
            page.get_by_role("button", name="预览修改").click(); time.sleep(1.5)
            expect(page.inner_text("#right-title") == "预览修改", "尺寸修改先进入预览")
            expect(revision() == start, "预览不改变版本")
            page.get_by_role("button", name="取消").click(); time.sleep(0.6)
            expect(revision() == start, "取消后版本不变")

            size_inputs().nth(1).fill(str(float(size_inputs().nth(1).input_value()) + 2))
            page.get_by_role("button", name="预览修改").click(); time.sleep(1.5)
            page.get_by_role("button", name="采用修改").click(); time.sleep(1.5)
            adopted = revision()
            expect(adopted != start, "采用尺寸后版本递增")
            page.locator("#undo-button").click(); time.sleep(1.5)
            expect(revision() != adopted, "撤销会生成恢复版本")
            page.locator("#redo-button").click(); time.sleep(1.5)
            expect(revision() not in (start, adopted), "重做继续生成版本")

            page.locator("#tree .row").filter(has_text="座板").first.click(); time.sleep(0.4)
            page.locator('[data-tool="translate"]').click(); time.sleep(0.3)
            page.evaluate("""() => {
              const viewport = window.__editorViewport;
              viewport.setSelection('seat'); viewport.setTool('translate');
              viewport.transform.object.position.x += 8; viewport.commitTransform();
            }""")
            time.sleep(1.2)
            expect(page.inner_text("#right-title") == "预览修改", "拖拽后先进入预览")
            expect("拖动到" in page.inner_text("#right-body"), "拖拽预览显示位置")
            page.get_by_role("button", name="取消").click(); time.sleep(0.6)

            page.locator("#tree .row").filter(has_text="座板").first.click(); time.sleep(0.4)
            page.locator("#right-body details summary").first.click(); time.sleep(0.3)
            hole = page.locator("[data-hole][data-hole-field='u_mm']").first
            hole.fill(str(float(hole.input_value()) + 1))
            page.get_by_role("button", name="预览孔槽参数").click(); time.sleep(1.2)
            expect(page.inner_text("#right-title") == "预览修改", "孔位修改先进入预览")
            page.get_by_role("button", name="取消").click(); time.sleep(0.6)

            page.locator('[data-tool="measure"]').click(); time.sleep(0.3)
            page.mouse.click(700, 450); time.sleep(0.4)
            page.mouse.move(820, 380); time.sleep(0.6)
            expect("mm" in page.inner_text("#measure-hud"), "测量悬停显示实时距离")
            page.keyboard.press("Escape"); time.sleep(0.3)
            expect(not page.locator("#measure-hud").is_visible(), "Esc 退出测量")

            page.locator('[data-action="check"]').click(); time.sleep(1.5)
            expect(page.inner_text("#right-title") == "检查", "检查按钮打开检查面板")
            expect("structural_coverage" in page.inner_text("#right-body"), "检查包含覆盖边界")
            page.locator("#cut-button").click(); time.sleep(1.5)
            expect(page.inner_text("#right-title") == "开料", "开料按钮打开整板排板")
            expect(page.locator("#right-body svg").count() >= 1, "开料页有整板 SVG")

            # ---- PS: honest refusal + package path -----------------------------
            open_project(ps_id)
            page.locator("#tree .row").filter(has_text="座板").first.click(); time.sleep(0.4)
            size_inputs().nth(1).fill(str(float(size_inputs().nth(1).input_value()) + 2))
            page.get_by_role("button", name="预览修改").click(); time.sleep(1.5)
            expect("尚无已验证的尺寸关联" in page.inner_text("#right-body"), "无关联尺寸给出可行动的错误，不假装预览")
            expect(revision() == "v1", "拒绝修改时不写版本")

            page.locator('[data-action="check"]').click(); time.sleep(1.5)
            expect(page.inner_text("#right-title") == "检查", "PS 参考模型可运行检查")
            page.locator("#docs-button").click(); time.sleep(1.2)
            expect(page.inner_text("#right-title") == "文档", "文档按钮打开版本列表")
            page.get_by_role("button", name="生成当前版本加工包").click(); time.sleep(4)
            expect(page.locator("#right-body a").count() >= 2, "生成后出现 PDF / ZIP 链接")

            page.reload(wait_until="networkidle"); page.wait_for_selector("#viewport canvas"); time.sleep(1.2)
            delivery = page.locator("#right-body select").first
            delivery.select_option("kit")
            page.get_by_role("button", name="应用交付方式").click(); time.sleep(1.5)
            expect(delivery.input_value() == "kit", "交付方式切到 kit 并保持")
            expect(revision() != "v1", "交付方式写入新版本")

            expect(not errors, "浏览器无脚本异常")
            browser.close()
    except Exception as error:
        print(f"\nFAIL  {error}")
        return 1

    print(f"\nPASS  {checks} interaction checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
