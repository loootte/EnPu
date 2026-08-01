# 结构优先分层识别内核（#58）

> 状态：已落地可开关路径（`ENPU_PIPELINE_MODE=structure`）  
> 默认仍为 `legacy`（OCR 整页 → 规则拼装），避免打断现有桌面闭环。

## 1. 动机

实践结论：

- **音高数字 OCR 已可用**
- **小节线 / 时值线 / 高低音点等图形符号**靠 OCR 文本流不稳定
- 双谱对照下，结构错位会被放大

根因：过早依赖 OCR 文本顺序。时值、八度、小节边界首先是**图形与空间关系**。

## 2. 分层模型（目标架构）

与 Issue [#58](https://github.com/loootte/EnPu/issues/58) 对齐：

```text
L1  页面级
    ├── 标题
    ├── 调号
    ├── 拍号
    └── 主谱面（score region）

L2  主谱面
    └── 谱行（systems / rows）
        └── 同一逻辑行：pitch 数字带 + 和弦 + 歌词 + 时值下划线带（绑定，非并列伪谱行）

L3  谱行内（#85 分割线模型）
    ├── 主存：有序纵向 **splits**（行内分割线 x；全图像素）
    ├── 派生：measures = [L2.x1, …splits, L2.x2] × [L2.y1, L2.y2]
    └── Score.measures 与派生 L3 一一对应（#66 对齐；#85 端点为 L2 边界）

L4  小节内元素
    ├── 音符候选（pitch ROI，应覆盖数字 + 时值线 + 高低音点 + 附点/延音线区域）
    ├── 和弦标识（独立 kind，不并入 pitch 框）
    ├── 歌词（独立 kind）
    └── 拍号约束下的小节时值校验（与 L5 时值联动）

L5  音符内部
    ├── 音高数字          ← 此阶段使用 OCR（+ 几何模板兜底）
    ├── 时值线（减时值下划线）
    ├── 高低音点（octave dots）     ← 见 #72
    ├── 附点 / 延音线               ← 见 #72
    └── 升降记号（后续）
```

### 原则

| 层级 | 手段 |
|------|------|
| L1–L4 | **OpenCV / 几何 / 版面分析**为主，不依赖整页 OCR 阅读顺序 |
| L5 | **音高数字**以 OCR 为主，并与同节点几何特征绑定 |
| 组装 | IR → EnPu `Score` v0.1；编辑 / 试听 / 导出路径不变 |

## 3. 建议流水线（实现顺序）

1. 预处理（倾斜、缩放等；坐标仍回写到输入图像空间）
2. **L1** 版面：标题 / 调号拍号 / 主谱面 ROI（#60 等）
3. **L2** 谱行：水平投影 → 行类型 → pitch+chord+lyric 绑定（#61）
4. **L3** 行内纵向分割线检测 → 派生小节矩形（#85；旋律带检线 #84）
5. **L4** 小节内候选音符 / 和弦 / 歌词 ROI（#69）；拍号时值校验元数据
6. **L5** 局部 ROI：OCR 音高 + 时值线 / 点 / 线几何 → `NoteGlyph`
7. **assemble**：IR → `Score`；可选 meter soft-fit
8. 桌面 `structure` 叠图：L1–L5 框 + **可编辑分割线**（L3）

## 4. 代码布局

| 路径 | 职责 |
|------|------|
| `core/app/pipeline/structure/ir.py` | PageLayout / StaffSystem / SplitLine / Measure / NoteCandidate / NoteGlyph |
| `l1_page.py` | 页面区域（title / key_time / score） |
| `l2_systems.py` | 谱行检测与 pitch+chord+lyric 绑定（#61） |
| `splits.py` | `splits ↔ measures` 纯函数、规范化 / 拖线 / 迁移（#85） |
| `l3_measures.py` | 行内检 split → 派生 measures（#85 / #84） |
| `l4_notes.py` | 小节内 pitch / chord / lyric 候选 ROI |
| `l5_glyph.py` | 局部 OCR + 几何时值 / 点；meter 校验 |
| `assemble.py` | IR → Score；结构调试 `structure` 字段 |
| `pipeline.py` | `run_structure_recognize` 串联 |

开关：

```bash
ENPU_PIPELINE_MODE=structure   # 结构优先
ENPU_PIPELINE_MODE=legacy      # 默认：现有 OCR→parse
```

### 桌面分层叠图（UI）

| 字段 | 说明 |
|------|------|
| `structure.items[]` | 各层框：`layer` L1–L5、`label`、`box`；L5 含 pitch/duration/underlines |
| `structure.items` L3 | `kind=measure_derived`：由 splits 派生，编辑模式下只读显示 |
| `structure.barlines[]` | **L3 主交互**：`{system,x,y1,y2,id,source,editable}` 纵向分割线 |
| `structure.summary` | 谱行 / 小节 / 候选 / 音高数量等 |

预览模式选 **结构**，左侧可开关 L1–L5。  
L3 编辑：拖动/增删 **分割线**；双谱高亮矩形与派生小节框对齐（见 [l3-split-model.md](./l3-split-model.md)）。

### 用户改框 + 局部重跑（#78）

| 项 | 说明 |
|----|------|
| UI | 结构面板「编辑模式」：点选 L1–L5 框，拖边角缩放 / 拖框移动 |
| API | `POST /v1/recognize/structure/rerun`：`from_layer` + `base_structure` + 可选 `edits` |
| 语义 | 从 `from_layer` 起重跑该层及下层；上层框与结果保留 |
| 实现 | `structure/rebuild.py` 从 structure 反序列化 IR；`run_structure_rerun` 按层分支 |

## 5. 与现有路径关系

```text
POST /v1/recognize
        │
        ├─ pipeline_mode=legacy ──► runner（Paddle 整页 OCR → parse）
        │
        └─ pipeline_mode=structure ──► structure.pipeline（L1–L5 → Score）
```

- 对外 API 形状不变（`RecognizeResponse` + `Score`）
- 结构模式 `meta.parse_warnings` 带 `pipeline=structure` 与各层日志
- `boxes` / `regions` 为音符候选 ROI（双谱调试）

## 6. 进度与后续

| 项 | 状态 |
|----|------|
| IR + L1–L5 脚手架 | 已落地 |
| L1 标题/谱面切分 | #60 |
| L2 pitch+chord+lyric 绑定 | #61 |
| L3↔Score 小节对齐 | #66 |
| L4 pitch 带 ROI / 和弦歌词分离 | #69 |
| 用户改任意层框 + 从该层重跑下层 | #78 |
| L4 高音点区域进 ROI | #71（部分：L4 上扩 pad，见 #72 实现） |
| L5 高/低音点、附点、延音线 + 小节时值校验 | #72 |
| 扫描件 L1 标题/L2 行区过大 | #64（自适应阈值 + 间隙/峰分割） |
| 末行短句漏检 | #65 |
| 时值线 / meter soft-fit（legacy 等） | #54 |

## 7. 相关

- Issue [#58](https://github.com/loootte/EnPu/issues/58)  
- [architecture.md](./architecture.md) · [README.md](../README.md)  
- 版面 #34、小节 #35、双谱 #45、时值 #54  
