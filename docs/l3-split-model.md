# L3 行内纵向分割线模型（Issue #85）

> 状态：已落地（识别 + 桌面拖线编辑 + 派生小节 + 双谱高亮对齐）

## 1. 模型

| 概念 | 说明 |
|------|------|
| **L2** | 谱行矩形 `bbox`（父级） |
| **L3 主存** | 行内有序 **interior splits**（全图像素 x） |
| **L3 派生** | 小节矩形 = `[x_left, …splits, x_right] × [y0,y1]`，y 取自 L2 |

坐标约定：**全图像素 x**（与叠图/双谱一致）。禁止与行内归一化混用。

```text
edges = [L2.x1, sorted(splits.x), L2.x2]
measure_i = [edges[i], edges[i+1]] × [L2.y1, L2.y2]
n_measures = n_splits + 1   # 无内线时整行 1 节
```

- 端点边界不可删除；只编辑内部分割线  
- 移动/增删线后必须重算 measures，保证不重叠、x 严格递增  

## 2. 识别

1. 在 L2 行内估计 **主旋律垂直带**（数字密集区，#84）  
2. 带内垂直形态学 / Hough / 投影 → 候选 x  
3. `normalize_splits`（间距、去重、夹紧）  
4. `splits_to_measures` 派生小节矩形  

失败：`splits=[]` → 整行一个 measure，`measure_source=whole_line`。

代码：

| 路径 | 职责 |
|------|------|
| `structure/splits.py` | 纯函数：normalize / splits↔measures / move·insert·delete |
| `structure/l3_measures.py` | 检测 + 写 `StaffSystem.splits` |
| `structure/ir.py` | `SplitLine`、`StaffSystem.splits` |
| `structure/assemble.py` | `barlines[]` 带 id/source；L3 item `kind=measure_derived` |
| `structure/rebuild.py` | 用户改线后从 barlines 重算 measures |

## 3. 桌面编辑

| 操作 | 行为 |
|------|------|
| 拖动红/黄竖线 | 改 split.x，夹紧相邻线之间 |
| 添加区域（L3） | 在拖框中心 x 插入 `source=user` split |
| 双击分割线 | 删除该线 |
| 绿色小节框 | **只读**派生显示（`measure_derived`） |

结构层选 **L3 分割线** 进入编辑。改线后 `structureDraft` 会 `rederiveMeasuresFromSplits`。

## 4. 双谱高亮对齐

`measureRectsFromStructure` 必须包含 `kind=measure_derived`，并优先使用 **编辑草稿** `structureDraft`，使：

- 原稿高亮矩形与分割线对齐  
- 拖线后高亮实时跟随  

实现：`desktop/src/lib/measureLayout.ts` · `RecognizePage` 的 `allMeasureRects`。

## 5. 评估与 GT

- **线级主指标**（`L3_barlines` / `barline_x_metrics`）：  
  `split_count_mae`、`split_mean_abs_x_error`、`split_fp` / `split_fn`  
- **派生框 IoU**：次要回归用  
- 编辑框作 GT：`structureToEvalGt` 写入 `layers.L3.splits` + `barlines`（#86 / #88）  
- 单层调优目标可对齐线级 loss（#89）  

## 6. 迁移

旧数据仅有 measure 矩形：

```text
measures_to_splits → 相邻框共享边界 x → interior splits
```

下游 L4 / Score 仍消费派生 `measures`，无需一次改完。

## 7. 相关

- [#84](https://github.com/loootte/EnPu/issues/84) 旋律带小节线  
- [#66](https://github.com/loootte/EnPu/issues/66) Score ↔ L3 对齐  
- [#86](https://github.com/loootte/EnPu/issues/86) / [#89](https://github.com/loootte/EnPu/issues/89) 分层评测与单层调优  
- [architecture-structure-first.md](./architecture-structure-first.md)  
