# 两把椅子的验收产物

2026-11-24 · 由 `scripts/verify_two_chairs.py` 生成，同一份仓库数据、同一版本。

PDF 采用**混合版式**：
- A4 竖版：第 1 页汇总封面、第 2 页采购、第 3 页预算、第 4 页交付与装配文字。
- A3 横版：整板下料图、每张加工图/大样各一页；不再把横版图纸压进竖版。
- 表格改为按内容自适应列宽，长材料名不再被挤成两行，数量列收窄。

```
PYTHONPATH=. .venv/bin/python scripts/verify_two_chairs.py
```

## 结果

| | CAFE CHAIR | PS 2026 |
|---|---|---|
| 性质 | 仓库改制样例 | 公开资料参考重建 |
| 版本 | v1 | v1 |
| 板件 / 连接 | 6 / 5 | 6 / 6 |
| 状态 | ready | ready |
| 整板 | 1 张 24 mm | 1 张 18 mm |
| 材料 | 480.00 | 420.00 |
| 五金 | 28.80 | 54.00 |
| 加工 | 280.00 | 310.00 |
| 表面 | 180.00 | 200.00 |
| 合计 | **968.80 CNY** | **984.00 CNY** |

文件：

- `cafe-chair-v1.pdf` / `cafe-chair-v1.zip`（16 页 / 22 个包文件）
- `ps2026-reference-v1.pdf` / `ps2026-reference-v1.zip`（12 页 / 18 个包文件）
- `cafe-cover.png` / `ps-cover.png`（第一页预览）
- `ps-procurement-auto.png`（自适应表格）
- `cafe-assembly-a4.png` / `cafe-cut-a3.png` / `cafe-drawing-a3.png`（混合版式预览）
- `two-chairs-summary.json`

## 必须说明

- 价格是**示例费率**，不是加工店报价；PS 2026 材料/加工同样是示例。
- PS 2026 是参考重建：矩形近似、464 mm 近似 480 净宽、孔位推断，不等于原版尺寸。
- PS 2026 的 cam lock 用 Ø15 锁孔 + Ø6.5 销孔近似；锁紧行程、偏心轮位置、沉孔未表达。
- 承载、连接强度、稳定性、加工公差和实物装配仍未验证（包里的 `structural_coverage` / `fit_coverage`）。
- 包状态 ready 表示“当前审查规则下可以出包”，不表示结构安全或加工店已接受。
