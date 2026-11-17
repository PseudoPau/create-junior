# 架构与 AI 边界

## 分层

```text
Web 工作台
  ↓
Workbench API（版本、参考、候选、检查、导出）
  ↓
Project Store（本地 JSON + 不可变版本 + 乐观锁）
  ↓
Design Domain（部件、材料、加工、连接、五金、证据）
  ↓
Deterministic Engine（几何、连接、制造检查、图纸和清单）

AI Designer Orchestrator
  ├─ OpenAI-compatible provider
  ├─ Local model provider（后续）
  └─ Session handoff（人工触发，候选导入）
```

设计数据只有一个事实源：`Project`。三维模型、检查、图纸、清单和 ZIP 都从当前项目派生；AI 输出只是一份基于 `base_revision` 的 `DesignProposal`。

## AI 提案协议

提案至少包含：

- `base_revision`：生成时看到的项目版本。
- `summary`：用户可读的设计理由和限制。
- `patch`：只允许写入 `EDITABLE_FIELDS` 的结构化变更。
- `assumptions`、`affected_ids`：假设与受影响对象。
- `provider`、`autonomy`：来源和边界声明。

流程是 `生成 → 字段校验 → 确定性检查 → 候选预览 → 用户接受 → 新版本`。任何版本变化都会使旧提案失效。

## 自主性边界

AI 可以自主决定支持范围内的部件拆分、参数、材料候选、连接顺序和加工方式；它必须把不可见信息标成未知，把新连接标成未确认，把不支持的几何保留为缺项。AI 不能直接写当前版本、不能把未知改成已确认、不能确认承载/安全、不能发布加工包。

产品服务承担最终门槛：版本冲突、字段契约、几何合法性、孔槽位置、连接跨件关系、加工覆盖率和发布确认。这样更换模型或供应商不会改变产品规则。

## 提供方策略

`app/workbench/ai.py` 隔离 OpenAI-compatible HTTP 接入。会话模式由 API 保存带 revision 的请求，经当前聊天处理后通过 import 返回候选；它不是一个自动运行的本地模型。显式样例入口在独立项目加载现成 CAFE CHAIR 候选，不消费用户参考。三条通道都不能自行确认或发布。`/ai/status` 只返回连接模式、模型名和字段填写布尔值，不返回密钥。

## 数据生命周期

参考资料和项目版本落在 `.data/workbench/<project-id>/`。候选单独保存，接受时由 Store 以乐观锁写入新版本；确认状态在任何设计修改后清除。导出包读取并锁定用户指定的当前版本，不读取旧候选。
