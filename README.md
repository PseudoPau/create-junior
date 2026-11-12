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

## 当前阶段

阶段 0：项目骨架和 DesignManifest 数据模型。

Airport 连接、外部 AI、参考图分析和加工包生成将在后续阶段加入。项目数据默认保存在 `.data/`，不使用数据库。
