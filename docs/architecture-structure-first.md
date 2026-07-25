# 结构优先分层识别内核（#58）

> 状态：**脚手架已落地**（`ENPU_PIPELINE_MODE=structure`）  
> 默认仍为 `legacy`（OCR 整页 → 规则拼装），避免打断现有桌面闭环。

## 1. 动机

实践结论：

- **音高数字 OCR 已可用**
- **小节线 / 时值线 / 高低音点等图形符号**靠 OCR 文本流不稳定
- 双谱对照下，结构错位会被放大

根因：过早依赖 OCR 文本顺序。时值、八度、小节边界首先是**图形与空间关系**。

## 2. 分层模型

```text
L1  页面级     标题 / 调号拍号 / 主谱面 ROI
L2  主谱面     谱行（systems）
L3  谱行       小节（measures）+ 小节线
L4  小节内     音符候选位（NoteCandidate ROI）
L5  音符节点   音高数字 OCR + 时值线/高低音点几何  ← OCR 主要在此
```

原则：**L1–L4 以 OpenCV / 几何为主；L5 对局部 ROI 做 OCR 并绑定几何特征。**

## 3. 代码布局

| 路径 | 职责 |
|------|------|
| `core/app/pipeline/structure/ir.py` | 中间表示 PageLayout / StaffSystem / Measure / NoteCandidate / NoteGlyph |
| `l1_page.py` | 水平投影划分页面区域 |
| `l2_systems.py` | 谱行检测：pitch 与 chord/lyric/underline 绑定为同一 system（#61） |
| `l3_measures.py` | 小节线 + 小节切分（复用 `barlines.detect_barline_xs`） |
| `l4_notes.py` | 小节内连通域 / 投影 → 音符候选 |
| `l5_glyph.py` | 局部 ROI OCR + 下划线 / 八度点 |
| `assemble.py` | IR → `Score` v0.1 |
| `pipeline.py` | `run_structure_recognize` 串联 |

开关（环境变量）：

```bash
ENPU_PIPELINE_MODE=structure   # 结构优先
ENPU_PIPELINE_MODE=legacy      # 默认：现有 OCR→parse
```

### 桌面分层叠图（UI）

结构模式识别成功后，响应含 `structure` 字段：

| 字段 | 说明 |
|------|------|
| `structure.items[]` | 各层框：`layer` L1–L5、`label`、`box`、L5 另有 `pitch/duration/underlines` |
| `structure.barlines[]` | 小节线竖线 `{system,x,y1,y2}` |
| `structure.summary` | 谱行/小节/候选/音高数量等 |

桌面左侧「结构分层叠图」可开关 L1–L5；预览模式选 **结构** 即可叠图查看。

## 4. 与现有路径关系

```text
POST /v1/recognize
        │
        ├─ pipeline_mode=legacy ──► runner._run_on_bgr（Paddle 整页 OCR → parse）
        │
        └─ pipeline_mode=structure ──► structure.pipeline（L1–L5 → Score）
```

- **对外 API 形状不变**（`RecognizeResponse` + `Score`）
- 结构模式下 `meta.parse_warnings` 带 `pipeline=structure` 与各层日志
- `boxes` / `regions` 输出为 **音符候选 ROI**（便于双谱叠图调试）

## 5. 验收与后续子任务

本脚手架验收：

- [x] 存在 IR 与 L1–L5 模块，且顺序可从日志证明
- [x] `structure` 模式可返回合法 Score（mock 可通）
- [x] `legacy` 默认不回归

后续（建议拆子 Issue）：

1. L1 调号/拍号专用检测与 OCR 带增强  
2. L3 小节线召回/精确率评测（真实谱 mean \|Δbars\|）  
3. L5 时值线/八度点与 #54 几何对齐  
4. 结构叠图调试 API / 桌面可视化  
5. print_clear F1 不回退门槛下的 A/B 评测  

## 6. 相关

- Issue [#58](https://github.com/loootte/EnPu/issues/58)  
- 版面过滤 #34、小节 #35、双谱 #45、时值 #54  
