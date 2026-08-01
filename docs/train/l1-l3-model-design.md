# L1–L3 学习模型技术方案

> 状态：设计定稿 v0.1（#94 / 父任务 #92）  
> 数据契约：[`l1-l3-data-spec.md`](./l1-l3-data-spec.md)（`layout_schema_version` **0.1**）  
> 实现骨架：训练 Framework **#95**；core 推理插件为 **P2**（另开 Issue）

---

## 1. 目标与非目标

### 1.1 目标

用监督学习替代/增强当前 OpenCV 几何规则，直接预测 **L1–L3 布局**：

| 层 | 学习输出 | 与恩谱语义一致 |
|----|----------|----------------|
| L1 | 页面区框（至少 `score_region`） | `structure.items` L1 |
| L2 | 水平谱行 `systems[]` | `structure.items` L2 |
| L3 | 行内有序 **interior splits** 的 x | `structure.barlines` / IR `SplitLine` |

输出最终必须能转成现有 **`structure` / IR**，桌面叠图与编辑协议不变。

### 1.2 非目标（本设计阶段）

- 不实现训练代码（→ #95）
- 不在本设计中落地 core 推理插件完整代码（P2）
- 不做 L4 ROI / L5 音高端到端大模型
- 不承诺首版精度超过现有几何基线（先闭环：数据 → 训 → 评 → 导出）

---

## 2. 任务定义（仅 L1–L3）

坐标一律为 **全图像素**（与 data-spec / 桌面一致）。禁止在训练标签与推理输出之间混用「行内归一化 x」而不写明反变换。

### 2.1 L1 — 页面区域

| 项 | 说明 |
|----|------|
| 输入 | 全图 \(I \in \mathbb{R}^{H\times W\times 3}\)（可缩放后训，推理回写原图坐标） |
| 输出 | 类别框：`score`（必选）、`title` / `key_time`（可选） |
| 类型 | **目标检测**（推荐）或语义分割再提框 |
| GT | `layout.l1.score_region` / `title` / `key_time` |

**召回优先**：`score_region` 漏检会阻断 L2/L3；宁可框略大，后处理可裁。

### 2.2 L2 — 谱行 systems

| 项 | 说明 |
|----|------|
| 输入 | **MVP-A**：score ROI 裁切（推荐）；备选全图 |
| 输出 | 水平矩形 `systems[]`，阅读序 top→bottom |
| 类型 | 目标检测（单类 `system`）或多行实例分割 |
| GT | `layout.l2.systems[].bbox` |

语义对齐 #61：一个 system = 旋律行绑定后的行框（可含和弦/歌词带高度），**不是**逐像素五线。

### 2.3 L3 — 行内纵向 splits

| 项 | 说明 |
|----|------|
| 输入 | **单行 ROI**（L2.bbox 裁切，可略 pad）；条件为「已知一行」 |
| 输出 | 该行 **interior** 分割线 x 列表（全图或行内相对，导出时统一回全图） |
| 类型 | 见 §3 主路径（1D 热力 / 关键点 / 序列） |
| GT | `layout.l3.rows[i].splits[].x` |

派生：

```text
edges = [L2.x1, sorted(splits.x), L2.x2]
n_measures = n_splits + 1
measure boxes = 相邻 edges × L2.y   # 仅下游使用，非学习主目标
```

**禁止**把「无约束自由小节矩形」作为 L3 唯一学习目标（与 #85 冲突）。

---

## 3. 主路径选型

### 3.1 路径 A — 务实 MVP（**选定**）

```text
                    ┌──────────── L1 head: det (score/title/key_time)
全图 ──► Backbone ──┼──────────── L2 head: det (system)  [可在 score crop 上再跑]
                    └──────────── (可选) 共享特征

对每个 L2 框 crop ──► 轻量 L3 网络 ──► 1D split 热力 / 峰值 ──► normalize_splits
```

| 组件 | MVP 建议 | 备注 |
|------|----------|------|
| Backbone | 轻量 CNN（如 ResNet-18 / MobileNetV3 / 极简 U-Net encoder） | 数据少时优先小模型 |
| L1/L2 | 单阶段检测头（锚框或 anchor-free 中心点） | 类别少；可不引入完整 YOLO 全家桶 |
| L3 | **行 crop → 垂直压成 1D 或窄高特征 → 沿 x 的热力图**；峰值 = split 候选 | 与简谱竖线形态匹配 |
| 后处理 | NMS（框）；L3：`normalize_splits`（min_gap、夹紧 L2 内） | **复用** `core/.../splits.py` 语义 |
| 导出 | Torch `state_dict` + 可选 ONNX | #95 交付；core 加载 P2 |

**为何 L3 用热力/1D 而非再检竖线框：**  
行内问题本质是 **一维有序点集**；框检测会引入 y 自由度噪声，且与 #85 主存不一致。

### 3.2 路径 B — 数据极少时的补充（可选并行）

1. **合成预训**：渲染印刷简谱 / 程序化排版 → 自动 L1–L3 GT  
2. **真实工程微调**：data-spec 样本（如 `samples/layout/L001_*`）+ 增强  

路径 B 不改变任务定义与指标，只改数据配比。

### 3.3 MVP 范围冻结

| 阶段 | 范围 | 验收侧重 |
|------|------|----------|
| **MVP-1（#95）** | **L2 行框 + L3 行内 splits**；L1 可用规则或极简头 | toy 训通 + val 硬指标 |
| MVP-2 | L1 `score_region` 并入同骨干 | score 召回 |
| MVP-3 | title/key_time；多任务联合损失调权 | 页级完整 |

**#95 默认实现 MVP-1**；L1 可在 Framework 中留接口，首条 train 命令允许 `tasks: [l2, l3]`。

---

## 4. 网络与头设计（逻辑规格）

### 4.1 共享约定

- 训练分辨率：长边限制（如 1024 / 1280），保持宽高比，pad 到可整除 stride  
- 框标签：xyxy 全图像素 → 相对 feature map 编码（实现细节 #95）  
- L3 crop：对 L2 框 pad 2–4% 宽高，避免切掉边线墨迹  

### 4.2 L1 / L2 检测头

- 类别：L1 `{score, title, key_time}`；L2 `{system}`  
- 损失：分类 + 框回归（L1/GIoU/CIoU 任选一种，#95 固定一种并写清）  
- 推理：score 阈值 + NMS；L2 按 y 中心排序赋 `index`  

### 4.3 L3 1D 分割头（主推）

对行 crop 宽 \(W_r\)、高 \(H_r\)：

1. 特征提取 → 沿高度全局池化或 stride 压到 \(1 \times W'\)  
2. 输出 **热力** \(h \in [0,1]^{W'}\)（sigmoid）  
3. GT 构造：每个 split.x 映射到 \(W'\) 上高斯峰（σ 与行宽成比例，如 0.5–1.5% 行宽）  
4. 损失：BCE / focal on heatmap；可选峰值邻域加权  
5. 解码：非极大值抑制（1D NMS，min_gap 映射到像素）→ x 列表 → 反变换到全图  

**备选（不优先）：** 固定最大 K 条线的 x 回归 + 存在性 logits（变长用匈牙利匹配），实现成本更高。

### 4.4 多任务与分阶段

| 模式 | 说明 |
|------|------|
| 分阶段 | 先训 L2，冻结构再训 L3（数据少时稳） |
| 联合 | L2+L3 联合，L3 用 **GT L2 crop** 训、用 **pred L2** 评（报告两套） |

MVP 训练默认：**L3 用 GT 行框 crop**（避免误差耦合）；验证集额外报 **级联**（pred L2→L3）。

---

## 5. 损失与指标

### 5.1 训练损失（逻辑）

| 头 | 损失 | 权重（初值） |
|----|------|--------------|
| L1 | \(\mathcal{L}_{cls}+\mathcal{L}_{box}\) | 1.0；score 类可 ×1.5 |
| L2 | 同上 | 1.0 |
| L3 | \(\mathcal{L}_{heat}\)（+ 可选 count 正则） | 1.0–2.0 |

总损失 = 加权和；#95 配置 YAML 可调。

### 5.2 验证 / 报告指标（硬指标）

与现有分层评测（#86）对齐，**可复用概念**（不必同函数签名）：

| 层 | 主指标 | 说明 |
|----|--------|------|
| L1 | `score` IoU≥0.5 的 Recall / mAP@0.5 | 召回优先 |
| L2 | system 框 mAP@0.5；`system_count` MAE | 匹配用匈牙利 + IoU |
| L3 | **`split_count_exact` / `split_count_mae`**；匹配后 **`split_mean_abs_x_error`**；`split_fp/fn` | 与 `barline_x_metrics` / #85 一致 |
| 辅 | 派生 measure 框 mean IoU | **禁止作为唯一主指标** |

匹配 L3：对 GT/Pred 有序 x 做距离匹配（阈值如 12px 或 1% 行宽，取较大者写清）。

### 5.3 与几何规则 A/B

同一 val 集：

- `rule`：现有 `structure` 管线 L1–L3  
- `learned`：本模型  

对比 L2 mAP 与 L3 x-error；core 集成后可 `engine=rule|learned_l1l3` 切换。

---

## 6. 数据流

```text
.enpu.json / structure
        │  scripts/export_layout_gt.py  (#93)
        ▼
samples/layout/<id>/{layout.json, image.png}   ← layout_schema_version 0.1
        │  Dataset (#95)
        ▼
batch: image tensor + targets{l1,l2,l3}
        │  train loop
        ▼
ckpt / onnx
        │  (P2) core adapter
        ▼
structure.items + structure.barlines + IR
        │
        ▼
desktop 叠图 / 编辑 / rerun  不变
```

### 6.1 增强（建议）

- 几何：缩放、小角度旋转、平移、JPEG 噪声、对比度  
- **禁止** 水平翻转（破坏阅读方向与简谱习惯）  
- L3：可对 crop 做轻微横向 stretch，同步变换 split.x  

### 6.2 合规

| 规则 | 说明 |
|------|------|
| 训练图 | 仅授权 / 自有 / 仓库公开 samples |
| 商业敬拜谱 | 默认 **不进** 公开 git；放 `samples/private/layout/`（已 gitignore） |
| 发布权重 | 注明训练数据范围；勿打包未授权图 |

---

## 7. 与 core / structure 对接

### 7.1 字段对应表

| 模型输出 | structure / IR | 说明 |
|----------|----------------|------|
| L1 boxes | `items[]` layer=L1, kind=title\|key_time\|score | `assemble` / 叠图 |
| L2 boxes | `items[]` layer=L2, kind=system；`StaffSystem.rect` | 阅读序 index |
| L3 xs | `barlines[]` {system,x,y1,y2,id,source=detect}；`StaffSystem.splits` | **主存** |
| 派生 | L3 `items[]` kind=`measure_derived`；`MeasureLayout` | `splits_to_measures` |
| summary | width/height/n_systems/n_measures | 与现网一致 |

### 7.2 推理适配（P2 草图）

```text
ENPU_PIPELINE_MODE=structure
ENPU_STRUCTURE_ENGINE=rule | learned_l1l3   # 名称可改

learned_l1l3:
  1. 读图 → 模型 → layout 中间结果（同 data-spec 形状）
  2. layout → page_layout_from_structure 的逆：构造 StructureDebug
     或直接填 PageLayout(regions, systems.splits)
  3. 可选：L4–L5 仍走现有几何/OCR
  4. assemble → Score + structure debug
```

规则管线 **永久保留** 为 fallback 与 A/B。

### 7.3 后处理必须共享语义

- `normalize_splits(x_left, x_right, min_gap)`  
- `splits_to_measures(...)`  
- 与 UI 拖线编辑同一套约束，避免「训练一套、编辑一套」

---

## 8. 训练 Framework 接口预期（给 #95）

最小可实现切片（与 #95 验收对齐）：

| 模块 | 职责 |
|------|------|
| `data/` | 读 data-spec；collate；可视化图+框+竖线 |
| `models/` | L2 det ± L3 heat（L1 可选） |
| `metrics/` | L2 IoU/mAP；L3 count + mean_abs_x |
| `engine/` | train/eval loop、ckpt |
| `export/` | state_dict / ONNX + README「core 如何加载」段落 |
| `configs/mvp_l2_l3.yaml` | 任务开关、路径、超参 |

一条命令：`python scripts/train.py --config configs/mvp_l2_l3.yaml`  
数据：≥1 真实样本 + 合成/增强；至少 1 个 epoch 不报错。

---

## 9. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 真实标注极少 | 路径 B 合成预训；强增强；先 L3 行内（crop 相对易） |
| L2 误差传导 L3 | 训时 GT crop；评时分「oracle L2」与「级联」 |
| 旧工程 barlines 含外沿 | 已由 #93 导出转 interior；训练只见 data-spec |
| 与规则双轨漂移 | 统一 structure schema；共用 splits 后处理 |
| 模型过大难进 sidecar | MVP 轻量 CNN；ONNX + 可选 CPU |
| 把 measure IoU 当主指标 | 文档与 eval 脚本强制线级主指标 |

---

## 10. 分阶段路线图

```text
#93 data-spec ✅
    → #94 本设计 ✅
        → #95 Framework + toy 训练（MVP-1: L2+L3）
            → 扩充真实 layout 集 / 合成管线（P2）
            → core learned_l1l3 插件（P2）
            → L1 并入 + 与规则 A/B 报告
```

---

## 11. 验收对照（#94）

| 验收项 | 本文件位置 |
|--------|------------|
| 正式设计文档合入 | 本文 `docs/train/l1-l3-model-design.md` |
| 明确 MVP 范围与主路径 | §3.1 路径 A；§3.3 MVP-1 = L2+L3 |
| 与 data-spec 语义一致（L3=splits） | §2.3、§7.1 |
| structure 字段对应表 | §7.1 |

---

## 12. 相关

- 父任务 [#92](https://github.com/loootte/EnPu/issues/92) · 本任务 [#94](https://github.com/loootte/EnPu/issues/94)  
- 数据 [#93](https://github.com/loootte/EnPu/issues/93) · Framework [#95](https://github.com/loootte/EnPu/issues/95)  
- [#85](https://github.com/loootte/EnPu/issues/85) 分割线 · [#86](https://github.com/loootte/EnPu/issues/86) 指标 · [#89](https://github.com/loootte/EnPu/issues/89) 调优  
- [architecture-structure-first.md](../architecture-structure-first.md) · [l3-split-model.md](../l3-split-model.md) · [layer-metrics.md](../layer-metrics.md)  
