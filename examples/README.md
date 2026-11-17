# 设计样例

首次体验请优先使用网页的“从案例开始”入口，它会创建独立项目，无需准备参考图片。

`cafe-chair-manufacturing-proposal.json`、`cafe-chair-session-proposal.json` 和 `cafe-chair-hardware-proposal.json` 是开发过程中的结构化候选基线，展示部件、连接和加工特征。它们不等同于原物隐藏结构的测绘结果，也没有提供承载验证。

`prepare_cafe_reference.py` 是历史走查辅助脚本，要求本机 `.data/cafe-chair-reference/` 已有合法取得的 front.webp、side.webp、back.webp。这些参考图片不随源码提供；脚本不会自动下载它们。

`complete_cafe_manufacturing.py` 从既有 CAFE 设计生成加工候选，用于研究与复现。适用对象固定为该样例部件集，不是通用家具重建器。

产品构思与当前能力见根目录 README，实际走查见 docs/walkthrough-2026-11-17.md。
