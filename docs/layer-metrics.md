# 分层准确度量化（Issue #86）

> 状态：Core MVP（IoU / count / sequence 指标 + 批量 CLI + API）

## 能力概览

| 层 | 有几何 GT 时 | 仅有 Score GT 时 |
|----|--------------|------------------|
| L1 | 区域框 IoU P/R/F1 | 是否检出谱面（presence） |
| L2 | 谱行框 IoU | `system_count` 数量差 |
| L3 | 小节框 IoU；小节线 x 距离匹配 | `measure_count` / \|Δbars\| |
| L4 | 候选 ROI IoU | 音符 token 数 vs L4 pitch 框数（proxy） |
| L5 | — | 音高序列 LCS P/R/F1 |

统一结构：`LayerMetric`（tp/fp/fn、precision/recall/f1、mean_iou、mode、errors）。

## GT 扩展（可选几何）

在 Score v0.1 JSON 中增加：

```json
{
  "schema_version": "0.1",
  "parts": [ ... ],
  "extra": { "eval": { "pitch_sequence": ["1","2"], "measure_count": 4 } },
  "layers": {
    "L3": {
      "measures": [ { "box": { "x1":0,"y1":0,"x2":100,"y2":40 } } ],
      "barlines": [0, 50, 100]
    },
    "L4": {
      "notes": [ { "kind": "pitch", "box": { "x1":10,"y1":5,"x2":25,"y2":35 } } ]
    }
  }
}
```

无 `layers` 时自动退回 count / sequence 模式（仍可量化 L3 小节数、L5 音高）。

## CLI

```powershell
cd D:\workspace\EnPu
core\.venv\Scripts\python.exe scripts\eval-layers.py --run --engine mock --limit 5
core\.venv\Scripts\python.exe scripts\eval-layers.py --run --engine mock --out reports/layer-metrics.json --md reports/layer-metrics.md
```

## API

- `POST /v1/evaluation/compare` — 单样本 GT + structure/score → 分层 metrics  
- `POST /v1/evaluation/batch` — 批量 manifest 评测（`run_recognize` + engine）
- `POST /v1/evaluation/tune-param` / `tune-param/upload` — L3 参数网格扫描（缓存 L1/L2）
- `POST /v1/evaluation/baseline/diff` — 当前报告 vs 基线 mean_f1 差分
- `POST /v1/evaluation/baseline/save` · `GET /baseline/{name}` — 基线读写（`reports/baselines/`）

## Desktop（#86）

- 侧栏 **分层精度评测**：导入 GT → 对比当前识别 → F1 徽章 / P·R·F1 表
- 结构层按钮显示 F1 色标（绿≥0.8 / 黄≥0.5 / 红）
- 原稿 **误差叠图**：绿 TP / 红 FP / 黄 FN
- **L3 min_measure_width** 参数扫描 + 折线，标最优值

## 模块

```text
core/app/evaluation/
  types.py metrics.py gt_loader.py extract.py compare.py batch.py param_tuner.py
core/app/api/v1/evaluation.py
scripts/eval-layers.py
desktop/src/components/LayerMetricsPanel.tsx
```

## 后续

- 更多可扫参数（投影阈值、旋律带比例）
- 误差传导 L3→L4 连线高亮
- 批量评测结果直接在 UI 导入/对比基线  

