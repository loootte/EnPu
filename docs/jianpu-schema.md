# EnPu 简谱 JSON Schema v0.1

> **状态：v0.1 定稿**（Issue [#9](https://github.com/loootte/EnPu/issues/9)）  
> 机器可读：[`core/schemas/enpu-score-v0.1.json`](../core/schemas/enpu-score-v0.1.json)  
> Pydantic：[`core/app/schemas/score.py`](../core/app/schemas/score.py)  
> 示例：[`samples/scores/example-minimal.json`](../samples/scores/example-minimal.json)

---

## 1. 设计原则

1. **JSON 为内部真相源**；MusicXML / MIDI 仅作导出产物（#11）。  
2. v0.1 只覆盖敬拜场景高频子集：**单声部旋律 + 调号 + 拍号 + 可选速度 + 分音节歌词**。  
3. 音高用 **数字简谱度数** `1`–`7`（首调，相对 `key`）；高低点用 `octave` 相对八度。  
4. 时值先用 **西方时值名**（`quarter` / `eighth`…），便于 music21；简谱下划线语义由解析层（#10）映射。  
5. 扩展字段统一进 `extra`，避免破坏兼容。  
6. `schema_version` 固定为字符串 `"0.1"`；破坏性变更升主版本。

---

## 2. 顶层：`Score`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `schema_version` | `"0.1"` | 是 | 文档版本 |
| `title` | string | 否 | 曲名 |
| `key` | string | 否 | 调中心，推荐 `C`/`G`/`F`/`D`/`Bb`/`Eb`… |
| `time_signature` | string | 否 | 如 `4/4`、`3/4`、`6/8` |
| `tempo_bpm` | number \| null | 否 | 速度（BPM） |
| `parts` | Part[] | 是 | 声部列表；最小歌曲 1 个 `melody` |
| `meta` | ScoreMeta | 否 | 来源 / 引擎等 |
| `extra` | object | 否 | 扩展 |

---

## 3. `Part` / `Measure` / `NoteEvent`

### Part

| 字段 | 说明 |
|------|------|
| `id` | 稳定 id，默认 `P1` |
| `name` | 如 `melody` |
| `measures` | 小节列表 |

### Measure

| 字段 | 说明 |
|------|------|
| `number` | 从 1 起的小节号 |
| `notes` | 该小节内音符/休止符序列（顺序即时间顺序） |

### NoteEvent

| 字段 | 类型 | 说明 |
|------|------|------|
| `pitch` | `"1"`…`"7"` \| null | 度数；休止符必须为 null |
| `accidental` | `sharp`/`flat`/`natural` \| null | 临时升降 |
| `octave` | int -3…3 | 相对中音：`+1` 高点，`-1` 低点 |
| `duration` | enum | `whole`/`half`/`quarter`/`eighth`/`sixteenth`/`thirty_second` |
| `dots` | 0–2 | 附点个数 |
| `is_rest` | bool | 休止符 |
| `lyric` | string \| null | 对齐到该音的歌词音节 |
| `tie` | `start`/`stop`/`continue` \| null | 连音（v0.1 预留） |
| `extra` | object | 扩展 |

**约束：**

- `is_rest=true` ⇒ `pitch` 必须为 null  
- `is_rest=false` ⇒ `pitch` 必填为 `1`–`7`  

---

## 4. 最小完整示例

单声部 + 歌词（两小节）：

```json
{
  "schema_version": "0.1",
  "title": "示例诗歌（最小）",
  "key": "C",
  "time_signature": "4/4",
  "tempo_bpm": 80,
  "parts": [
    {
      "id": "P1",
      "name": "melody",
      "measures": [
        {
          "number": 1,
          "notes": [
            { "pitch": "1", "octave": 0, "duration": "quarter", "dots": 0, "is_rest": false, "lyric": "主" },
            { "pitch": "2", "octave": 0, "duration": "quarter", "lyric": "恩" },
            { "pitch": "3", "octave": 0, "duration": "quarter", "lyric": "典" },
            { "pitch": "5", "octave": 0, "duration": "quarter", "lyric": "够" }
          ]
        },
        {
          "number": 2,
          "notes": [
            { "pitch": "5", "octave": 0, "duration": "half", "lyric": "我" },
            { "pitch": "3", "octave": 0, "duration": "quarter", "lyric": "用" },
            { "is_rest": true, "duration": "quarter" }
          ]
        }
      ]
    }
  ],
  "meta": {
    "created_by": "enpu-schema-v0.1",
    "comments": "Minimal single-voice + lyrics example for issue #9."
  }
}
```

仓库内完整文件：`samples/scores/example-minimal.json`。

---

## 5. 与识别 API 的关系

| 层级 | 模型 | 阶段 |
|------|------|------|
| OCR 原始 | `RecognizeResponse.texts` / `boxes` | #2–#3 |
| 轻量提示 | `NoteHint`（度数抽取） | #3 |
| **结构化乐谱** | **`Score` v0.1** | **#9（本文）→ #10 解析填充** |
| 导出 | MusicXML / MIDI | #11 |

识别流水线最终应产出（或可转换成）`Score`，编辑器以 `Score` 读写。

---

## 6. Pydantic 用法

```python
from app.schemas.score import Score, example_minimal_score

score = example_minimal_score()
data = score.model_dump(mode="json")
score2 = Score.model_validate(data)
assert score2.schema_version == "0.1"
assert score2.melody_part() is not None
```

校验 JSON Schema 文件（可选，需 `jsonschema` 包）：

```bash
# 开发依赖可选
pip install jsonschema
python -c "..."
```

---

## 7. 标注规范（人工校对 / 数据集）

用于 Phase 1 评测集与人工修正：

1. **一音一音节**：`lyric` 尽量对应简谱下每个时值单元；多字占一拍时合并到该 `NoteEvent.lyric`。  
2. **小节号连续**：`Measure.number` 从 1 递增，不跳号。  
3. **拍号内满拍**：v0.1 不强制校验小节时值之和；标注时仍应按 `time_signature` 填满。  
4. **休止符**：用 `is_rest=true`，不要用 `pitch="0"`。  
5. **高低音点**：只改 `octave`，不要发明 `pitch="1."` 字符串。  
6. **调号**：写入 `key` 字母名；简谱「1=C」可另存 `extra.jianpu_key="1=C"`。  
7. **版权**：标注数据与 `samples/` 同样遵守自制/授权规则。

---

## 8. 非目标（v0.1 不做）

- 多声部对齐、合唱分部自动分配  
- 反复跳跃、D.C.、括号小节  
- 倚音、波音、滑音等装饰音  
- 和弦标记、吉他谱  
- 完整简谱排版坐标（版式层另议）

上述可通过 `extra` 试验，不进入 v0.1 必选字段。

---

## 9. 版本演进

| 版本 | 说明 |
|------|------|
| `0.1` | 当前：单声部 + 歌词 + 基础时值 |
| `0.2`（计划） | 反复、多行歌词、更严的小节时值校验 |

破坏性变更必须提升 `schema_version`，并提供迁移说明。
