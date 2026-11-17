# 架构与 AI 边界

## 分层

```text
Web 工作台
  ↓
Workbench API（版本、参考、候选、检查、导出）
  ↓
Project Store（本地 JSON + 不可变版本 + 乐观锁）
  ↓
Design Domain（使用模块、部件、材料、加工、连接、五金、证据）
  ↓
Deterministic Engine（几何、连接、制造检查、图纸和清单）

AI Designer Orchestrator
  ├─ OpenAI-compatible provider
  ├─ Local model provider（后续）
  └─ Session handoff（人工触发，候选导入）
```

设计数据只有一个事实源：`Project`。三维模型、检查、图纸、清单和 ZIP 都从当前项目派生；AI 输出只是一份基于 `base_revision` 的 `DesignProposal`。

### Module 层

`Project.modules` 是人体工学与功能意图层，位于用户需求和物理几何之间。Module 表达使用者、姿态/动作、支撑或净空目标、约束、依据、状态以及受影响部件；`parts` 保持几何事实，`joints` 保持制造和装配事实。Module 不取代任何一层，也不能单独生成“可生产”结论。

建议的最小对象边界：

```text
Module
├─ kind：support / reach / clearance / storage / surface
├─ purpose：用户要完成的动作或使用目标
├─ anthropometry：使用者、姿态、身体条件
├─ target：宽、深、高、净空、角度等目标
├─ constraints：必须满足的范围或关系
├─ status：inferred / target / confirmed / conflict / needs_review
├─ source_ids：参考或用户依据
└─ affected_part_ids：由它驱动或需要复核的部件
```

数据流为 `参考/意图 → ModuleDraft → 用户确认 → DesignProposal(modules + parts) → 确定性检查 → 图纸与制作包`。用户修改 Module 时，提案同时更新受影响部件、孔位和连接，并使旧资料失效；用户直接修改部件时，相关 Module 进入 `needs_review`，避免双向静默覆盖。

首个 Module 只实现 CAFE CHAIR 的“坐姿支撑”，沿用现有 PUT 和 Proposal API，不急着新增 `/modules` 接口。第一阶段可先存储模块目标、关联部件和约束摘要，再逐步把公式与求解放入确定性规则层。AI 负责从参考和自然语言提取模块假设、追问和提出修改；规则层负责单位、约束、几何、版本和资料一致性。

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
