# L1–L3 布局训练数据规范（layout data-spec）

> 状态：v0.1（#93 / 父任务 #92）  
> 坐标：**全图像素**，与桌面叠图 / `structure` / IR 一致（原点左上，x 向右，y 向下）。  
> 与 **Score v0.1**（`docs/jianpu-schema.md`）**分离**：本规范只描述页面几何布局，不描述音高/时值语义。

---

## 1. 目标与边界

| 是 | 否 |
|----|----|
| L1 页面区（title / key_time / score_region） | Score 音符序列、歌词语义 |
| L2 谱行框 systems | L4 音符 ROI、L5 音高 OCR |
| L3 行内纵向 **splits**（主存）与可选派生 measures | 端到端音高模型标签 |

训练样本 = **图像 + layout JSON**。Score 仅可作可选页级 meta（title/key/time）。

---

## 2. 现有恩谱工程格式（输入真源）

桌面保存的 **`.enpu.json`**（`project_version: "0.2"`，`kind: "enpu-project"`）是人工校正后的可版本化样本。真实示例字段：

```text
{
  project_version: "0.2",
  kind: "enpu-project",
  title, score,                    # Score v0.1（语义，非 layout GT）
  source_image,                    # 原图文件名
  source_image_data_url,           # 可选 data:image/png;base64,...
  structure: {                     # 布局真源（导出用）
    pipeline: "structure",
    summary: { width, height, n_systems, n_measures, ... },
    items: [ { layer, id, label, kind, box, confidence? } ],  # L1–L5
    barlines: [ { system, x, y1, y2, id?, source? } ]         # L3 竖线
  },
  boxes?, regions?,                # OCR 遗留，layout 导出忽略
  meta: { engine, pipeline_mode, enpu_desktop },
  created_at, updated_at
}
```

### 2.1 `structure.items` 分层

| layer | kind（常见） | 含义 |
|-------|--------------|------|
| L1 | `title` / `key_time` / `score` | 页面区域 |
| L2 | `system` | 一条逻辑谱行（pitch+和弦+歌词绑定后的行框） |
| L3 | `measure` 或 `measure_derived` | 小节矩形（**派生**；旧工程多为 `measure`） |
| L4 / L5 | `note_roi` / `glyph` 等 | **本 data-spec 不导出** |

`box`：`{ x1, y1, x2, y2 }`，全图像素。部分工程在 box 上带多余 `score: null`，导出时忽略。

### 2.2 `structure.barlines`

| 字段 | 必选 | 说明 |
|------|------|------|
| `system` | 是 | 谱行索引（与 L2 `l2-sys{N}` 一致） |
| `x` | 是 | 竖线 x（全图） |
| `y1`, `y2` | 建议 | 叠图用；缺省取 L2 y |
| `id`, `source`, `editable`, `confidence` | 否 | #85 新字段；旧工程可无 |

**重要（旧工程兼容）：**

- #66 时期常见：`n_barlines ≈ n_measures + 1`（**含小节外沿** 的 edge 链）。  
- #85 规范：主存仅为 **interior splits**，`n_splits = n_measures - 1`，端点取 L2 `x1/x2`。  
- 导出器会将 edge 链 **去掉首尾** 转为 interior splits（见 `app.layout_gt.export`）。

---

## 3. 训练样本目录约定

```text
samples/layout/<sample_id>/
  layout.json          # 本规范 JSON
  image.png            # 或 .jpg；与 layout.image.path 相对本目录
```

也可用清单文件聚合多个样本（训练 Framework #95 再定）；单样本最低要求是 **一对** `layout.json` + 图像。

私有/商业谱建议放在 **不入库** 目录，例如 `samples/private/layout/`（见 `.gitignore` 约定）。

---

## 4. `layout.json` 字段表

### 4.1 根对象

| 字段 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `layout_schema_version` | string | 是 | 当前 `"0.1"`（**不是** `score.schema_version`） |
| `kind` | string | 建议 | `"enpu-layout-gt"` |
| `id` | string | 建议 | 样本 ID |
| `image` | object | 是 | 见下 |
| `meta` | object | 否 | 页级元数据（非几何） |
| `l1` | object | 是 | L1 |
| `l2` | object | 是 | L2 |
| `l3` | object | 是 | L3 |
| `source` | object | 否 | 导出来源（工程路径等） |

### 4.2 `image`

| 字段 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `path` | string | 是* | 相对样本目录的图像路径 |
| `width` | int | 强烈建议 | 像素宽 |
| `height` | int | 强烈建议 | 像素高 |
| `sha256` | string | 建议 | 图像内容哈希 |

\*若仅用 hash 存储图库可另议；MVP 用 path。

### 4.3 `meta`（可选）

| 字段 | 说明 |
|------|------|
| `title` / `key` / `time_signature` | 来自 Score 或工程标题 |
| `source_image_name` | 工程内原文件名 |
| `engine` | 识别引擎标记 |

### 4.4 L1

| 字段 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `score_region` | BBox | **是** | 主谱面 ROI |
| `title` | BBox | 否 | 标题区 |
| `key_time` | BBox | 否 | 调号/拍号区 |
| `regions` | list | 否 | 全量 L1（含 role） |

`BBox = { x1, y1, x2, y2 }`，要求 `x2≥x1`, `y2≥y1`。

### 4.5 L2

```text
l2.systems[]: {
  id: string,           # 如 l2-sys0
  index: int,           # 阅读序 0..n-1
  bbox: BBox,           # 谱行框
  kind?: "system",
  label?: string,
  confidence?: number
}
```

### 4.6 L3（主存 splits）

```text
l3.rows[]: {
  system_id: string,      # 对应 l2.systems[].id
  system_index: int,
  splits: [{              # 有序 interior 分割线
    id: string,
    x: number,            # 全图像素；严格在 L2.x1 < x < L2.x2
    y1?: number,
    y2?: number,
    source?: "user"|"detect"|"migrate"|"soft_gap",
    confidence?: number
  }],
  measures?: [{           # 可选派生，存盘则必须 n = n_splits+1
    id?, label?,
    box: BBox
  }]
}
```

**派生规则（与 #85 一致）：**

```text
edges = [L2.x1, sorted(splits.x), L2.x2]
measure_i = [edges[i], edges[i+1]] × [L2.y1, L2.y2]
n_measures = n_splits + 1   # 无内线 → 整行 1 节
```

校验器：若写出 `measures`，则强制 `len(measures) == len(splits) + 1`。

---

## 5. 工程 / structure → 训练样本映射

| 工程 / structure | layout 样本 |
|------------------|-------------|
| `structure.summary.width/height` | `image.width/height` |
| `source_image_data_url` / 旁路图 | `image.png` + `image.path` |
| L1 items (`kind` title/key_time/score) | `l1.title` / `key_time` / `score_region` + `regions` |
| L2 items `kind=system` | `l2.systems[]` |
| `structure.barlines[]` | → 按 system 分组 → **interior** `l3.rows[].splits` |
| L3 items measure 框 | 可选 `l3.rows[].measures`；若 barlines 缺失可由邻接框推 splits |
| `score.title/key/time_signature` | `meta.*`（非几何） |
| L4 / L5 / `boxes` / `regions` OCR | **不映射** |

实现：`core/app/layout_gt/` · CLI：`scripts/export_layout_gt.py`。

---

## 6. 负例 / 忽略约定

| 区域 | 是否标注 |
|------|----------|
| 页眉装饰、页码、与谱面无关的文字 | 不进入 L2 systems；可落在 score_region 外 |
| 纯歌词行（未绑入 melody system） | 默认 **不** 作为 L2；若 UI 已绑入 system 框则随 L2 保留 |
| 和弦带 / 歌词带 | 已包含在 L2 行框内（#61 绑定），不单独 L2 |
| 空白页边 | 不标 L3 splits |

---

## 7. 与 Score v0.1 的边界

| | Score v0.1 | layout GT 0.1 |
|--|------------|---------------|
| 版本字段 | `schema_version` | `layout_schema_version` |
| 内容 | 调号、拍号、小节音符 | 框与分割线几何 |
| 小节 | `parts[].measures[]` 语义列表 | 由 L2+splits **派生** 的几何框 |
| 用途 | 播放/导出/编辑 | 监督 L1–L3 检测模型 |

禁止把 Score 的 measure 序号当作唯一 L3 几何 GT（应用 splits / 框）。

---

## 8. 导出与校验

```powershell
# 从桌面工程导出样本目录
python scripts/export_layout_gt.py `
  --project "C:\Users\...\坐在宝座上圣洁羔羊A调.enpu.json" `
  --out samples/layout/L001_zuozai_baozuo

# 仅校验
python scripts/export_layout_gt.py --validate-only samples/layout/L001_zuozai_baozuo/layout.json
```

校验硬规则摘要：

1. `layout_schema_version` 存在  
2. L1 `score_region` 合法 BBox  
3. L2 systems 合法 BBox  
4. 每个 split.x 严格落在对应 L2 `(x1, x2)` 内且严格递增  
5. 若有 measures：`n_measures == n_splits + 1`  

---

## 9. 版本

| 版本 | 说明 |
|------|------|
| `0.1` | 初版：L1 regions + L2 systems + L3 interior splits；可选 derived measures |

破坏性变更必须 bump `layout_schema_version` 并更新本文件与 `core/app/layout_gt`。

---

## 10. 相关

- 父任务 [#92](https://github.com/loootte/EnPu/issues/92) · 本任务 [#93](https://github.com/loootte/EnPu/issues/93)  
- 模型方案 [#94](https://github.com/loootte/EnPu/issues/94) · [l1-l3-model-design.md](./l1-l3-model-design.md)  
- Framework [#95](https://github.com/loootte/EnPu/issues/95)  
- [#85](https://github.com/loootte/EnPu/issues/85) L3 分割线模型 · [l3-split-model.md](../l3-split-model.md)  
- [architecture-structure-first.md](../architecture-structure-first.md)  
- 桌面工程 I/O：`desktop/src/lib/projectIo.ts`（`project_version` 0.2）  
