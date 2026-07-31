# L3 行内纵向分割线模型（Issue #85）

## 模型

| 概念 | 说明 |
|------|------|
| **L2** | 谱行矩形 `bbox`（父级） |
| **L3 主存** | 行内有序 **interior splits**（全图像素 x） |
| **L3 派生** | 小节矩形 = `[x_left, …splits, x_right] × [y0,y1]`，y 取自 L2 |

坐标约定：**全图像素 x**（与叠图/双谱一致）。

## 切分规则

```text
edges = [L2.x1, sorted(splits.x), L2.x2]
measure_i = [edges[i], edges[i+1]] × [L2.y1, L2.y2]
```

- `n_measures = n_splits + 1`（无内线时整行 1 节）
- 端点边界不可删除；只编辑内部分割线

## 识别

在 L2 行内估计旋律带 → 竖线检测 → `normalize_splits` → `splits_to_measures`。

## 编辑（Desktop）

| 操作 | 行为 |
|------|------|
| 拖动红/黄竖线 | 改 split.x，夹紧相邻线之间 |
| 添加区域（L3） | 在拖框中心 x 插入 user split |
| 双击分割线 | 删除该线 |
| 小节绿框 | 只读派生显示 |

## 评估

- 主：`L3_barlines` 线级数量 + mean_abs_x_error（见 LayerMetric.extra）
- 次：派生 measure IoU

## 迁移

旧 measure 矩形：`measures_to_splits` 用相邻框共享边界生成 splits。
