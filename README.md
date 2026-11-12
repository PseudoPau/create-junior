# Create Junior

Create Junior 是一个轻量的本地网页木作助手。

当前目标是围绕 AA Stool 类双侧板凳，完成：

```text
参考网页/图片 → 结构候选 → 身体尺寸与材料 → 木作检查 → Airport 预览 → 加工包
```

## 开发

```powershell
uv run uvicorn app.main:app --reload
```

打开 <http://127.0.0.1:8000>。

## 当前能力

- 参考网页或本地图片保存到项目目录，并生成带未知项的结构分析；配置
  `CREATE_JUNIOR_AI_BASE_URL`、`CREATE_JUNIOR_AI_API_KEY`、`CREATE_JUNIOR_AI_MODEL`
  后使用 OpenAI 兼容视觉接口。
- `DesignManifest` 是版本化事实源；尺寸、材料、结构候选、接合确认和验证结果都从它派生。
- 首版包含 AA Stool 类双侧板凳的确定性部件推导、保守材料库、简化承载估算、加工包和 ZIP 导出。
- Airport 使用 typed MCP 的 `create_project_get`、`create_geometry_scene_import_topology_plan`、
  `create_scene_verify` 和预览工具。Airport 不可用时，项目和本地加工包仍可继续。

项目数据默认保存在 `.data/`，不使用数据库。加工包下载地址为
`/api/projects/<project_id>/fabrication-package/download`。

当前加工图是轻量 SVG 示意图，承载估算是早期筛查，不替代工程校核；接合方式需要用户确认后才适合提交 3D。
