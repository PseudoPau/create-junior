# 会话 Agent：领取、检查、返回设计

本轮由当前 Codex / Claude 会话承担设计 Agent。网页保存任务并显示进度，**不会自动唤醒聊天或调用在线模型**。用户把网页中的任务提示发到当前聊天后，Agent 使用下面的工具处理；处理期间用户可以留在模型工作台。

本地原型、固定案例和真实参考处理是三件不同的事。加载内置案例不能算作识别用户参考。

## 谁做什么

| 角色 | 负责 | 不负责 |
|---|---|---|
| 用户 | 提供参考、身体数据和偏好，判断像不像原椅子，决定改款与做法取舍，采用候选 | 判断孔轴是否正确、反复确认未改变的连接 |
| 会话 Agent | 理解资料，生成模型和建议，调用检查工具，修正失败项，提出必要问题 | 直接写当前设计、自己采用候选、替用户确认未知事实、宣布承载通过 |
| 程序 | 字段与几何检查、版本约束、预览和提交、联动更新、派生图纸与清单 | 将模型检查等同于整椅承载、舒适性或实物加工验证 |

Agent 的操作规则也随任务上下文返回：保留原版关系，不自行把保型信息标为 verified；不由坐高直接推算座板前后长度；材料与连接修改必须包含关联部件、孔位、五金与装配说明。

## 任务状态

| 状态 | 网页含义 | 下一步 |
|---|---|---|
| `waiting_for_session` | 已保存，等待当前会话处理 | Agent 领取 |
| `running` | 已领取，正在读取、建模或检查 | Agent 定期续租，调用工具 |
| `needs_input` | 需要补充一项信息 | 用户回答，任务回到等待领取 |
| `ready` | 候选已返回 | 用户在网页预览、采用或取消 |
| `failed` | 明确失败，诊断保留 | 修改要求后重新提交任务 |
| `cancelled` | 用户取消了处理 | 迟到结果不能写入 |
| `stale` | 当前设计版本已变化 | 按新版本重新提交任务 |
| `interrupted` | 处理会话中断或服务已重启 | 重新提交任务 |
| `completed` / `dismissed` | 返回的候选已采用 / 已取消 | 历史记录保留 |

一个项目同时只允许一个活动任务。重复提交同一任务返回原任务；不同任务需要先结束或取消现有任务。已有候选正在预览时不能被新任务覆盖。

领取租约为 180 秒，Agent 至少每两分钟发送一次 heartbeat。服务重启或租约超时后，下一次读取任务会将运行状态转成 interrupted；不会继续显示虚假的生成进度。等待用户回答不占运行租约。

## 实际处理步骤

先按项目 README 启动服务。以下命令在项目根目录执行，使用 `scripts/session_agent.py`，只访问本机 HTTP 服务，不调用模型供应商。将示例中的 `PROJECT_ID`、`RUN_ID`、`REVISION` 替换为网页任务或 pending 返回值。

**1. 找到请求并领取。**

```powershell
uv run python scripts/session_agent.py pending
uv run python scripts/session_agent.py claim --project PROJECT_ID --run RUN_ID --revision REVISION
uv run python scripts/session_agent.py context --project PROJECT_ID --run RUN_ID --output session-context.json
```

`context` 包含当前项目、不可变原版快照（若已有）、任务原文、用户补充、参考状态、候选字段契约及工作说明。必须实际查看图片 / PDF 页图，不能只读取文件名或 URL 就声称分析过。

**2. 读取参考并形成候选。**

网页文字使用已经解析并保存的内容；没有读到文字的链接显示 unread，Agent 应请求补图或解决读取问题。图片返回项目内部图片地址。PDF 默认提取前六页文字，同时提供逐页 PNG 地址；明确返回总页数、已选页码和未读页数。

读取后续 PDF 页面：

```powershell
uv run python scripts/session_agent.py context --project PROJECT_ID --run RUN_ID --pages 7,8 --output session-context-pages-7-8.json
```

`--pages` 从 1 开始，一次最多六页；该选择应用于任务内每份 PDF。页码越界会在对应参考中显示不可读原因。PDF 图片接口为 `/api/workbench/projects/{project_id}/references/{reference_id}/pages/{page_number}`。项目关联文件存储为 `references/{reference_id}`，不依据上传文件名或扩展名读取任意路径。

Agent 将候选写入本机 JSON 文件，最小结构：

```json
{
  "summary": "说明参考对应关系、修改内容和未确定信息",
  "patch": {
    "parts": [],
    "materials": {},
    "joints": []
  }
}
```

上例仅说明格式，不是有效设计。`patch` 中出现的数组和对象会**整字段替换**；没有修改的字段可以省略，修改部件数组时必须保留其他部件。完整结构以 context 返回的 contract 为准。

**3. 检查并修正。**

```powershell
uv run python scripts/session_agent.py heartbeat --project PROJECT_ID --run RUN_ID --revision REVISION
uv run python scripts/session_agent.py preview --project PROJECT_ID --run RUN_ID --revision REVISION --file candidate.json --output preview-result.json
```

读取 `repairable_issues`，根据具体对象与问题调整候选，再次 preview。每个任务最多三次候选检查，字段校验失败也计入次数。第三次仍有可修复问题时任务失败，保留问题和候选诊断。预览不写当前项目，也不提前暴露为可采用候选。

真实尺度、木纹方向、做法选择等缺失信息不会被当成几何错误无限重试；它们仍留在 checks 中，需要用户决定或补充，后续出包条件不会被跳过。

需要用户信息时，一次提一个具体问题：

```powershell
uv run python scripts/session_agent.py question --project PROJECT_ID --run RUN_ID --revision REVISION --text "请提供椅子的实测总高，或上传有尺寸的图纸。"
```

用户可以在网页回答，任务保留原参考、原始要求和问答历史，然后重新领取继续。不要因缺少尺度而编造加工尺寸。

**4. 返回最近一次检查通过的候选。**

```powershell
uv run python scripts/session_agent.py finish --project PROJECT_ID --run RUN_ID --revision REVISION --proposal PROPOSAL_ID
```

`PROPOSAL_ID` 来自最近一次 preview 的 proposal.id。finish 只返回这一份检查过的候选，不重新生成或重新计算。用户在网页按“继续”或“采用修改”才写入当前设计。模型、尺寸和加工资料使用同一版本。

**仅返回适己建议时，没有“先采用建议清单”的额外步骤。** Agent 应只提交 `modules` 字段，保留所有 Module 的顺序、身份、身体数据、目标、约束和状态，只更新 `suggestions` 与说明 `notes`。程序将它识别为 `result_kind=advice`：finish 返回 `advice_modules` 和说明，`proposal_id` 为空，不写入当前设计或候选入口。工作台直接按项展示建议；用户点击某项的“下一个”时才采用实际尺寸调整。只要同时改变目标值、身体快照、状态或几何，就仍然走正常设计候选流程。

建议绑定任务的项目版本。身体数据或设计发生变化后，旧建议不再直接套用；已采用的修改保持不变。建议中的 `anthropometry` 必须与本次 Module 的身体快照一致。已有模型检查问题保留在任务 checks 中，返回建议不会使这些问题消失，也不会宣称模型已经能出包。

无法完成时明确结束：

```powershell
uv run python scripts/session_agent.py fail --project PROJECT_ID --run RUN_ID --revision REVISION --text "该参考需要当前尚不支持的曲面结构，请提供平直板件参考。"
```

Agent 不能在失败后加载固定六板椅来伪装完成。

## 版本、恢复和工具边界

- 每次领取、预览、回答和返回都绑定 base_revision。用户修改项目后，旧任务不能覆盖新版本；重新读取任务和当前设计后建立新任务。
- 取消后迟到提交被拒绝。已返回但未采用的候选不会被另一任务覆盖。
- 默认 worker 名为 `codex-session`；多会话处理时用 `--worker` 指定不同名称，同一任务后续调用保持一致。
- API 仅用于本机原型，worker_id 是协作标识，不是公网认证凭据；服务保持本机监听。
- 任务文件与预览文件分别保存，当前 Project 只能通过用户采用接口更新。任务日志只记录操作、检查码、版本和结果，不记录隐式推理过程或密钥。
- 本轮的自动化部分是几何检查、联动、资料派生及状态保护；会话 Agent 需要当前聊天实际执行。网页独立在线 Agent 属于后续接入。

## 验证记录

`tests/test_design_runs.py` 覆盖任务幂等、三轮上限、错误修正、取消、版本过期、候选竞争、租约与重启、问答恢复、采用关联、建议免二次采用、建议与设计修改的边界、项目文件边界和 PDF 选页。测试不访问外部模型或真实项目。

实现时已做 Python AST 语法检查。遵循项目约定，本轮未由此任务运行单元测试、构建或完整回归；真实复原质量仍需独立参考走查，任务生命周期测试不能代替复原效果验收。
