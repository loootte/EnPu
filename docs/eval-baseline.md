# 识别准确率基准线（Issue [#29](https://github.com/loootte/EnPu/issues/29)）

> 状态：**评测集构建中**（合成 15 / 手动 5 待补）  
> 目标：可复现的 pitch / 小节划分基线，支撑 Phase 1 验收。

---

## 1. 数据集布局

```text
samples/eval/
  manifest.json          # 索引（E01–E15 + M01–M05）
  images/                # 合成曲谱 PNG
  gt/                    # Ground-truth Score v0.1 JSON
  manual/                # 用户真实曲谱（M01–M05）
    README.md
```

| 子集 | 数量 | 说明 |
|------|------|------|
| `print_clear` | 10 | 清晰印刷风格合成（E01–E10） |
| `scan_like` | 3 | 轻微噪声/旋转（E11–E13） |
| `cn_lyrics` | 2 | 中文标题/歌词行（E14–E15） |
| `manual_real` | 5 | **待你放入**正在用的曲谱（M01–M05） |

生成合成集：

```powershell
cd D:\workspace\EnPu
python scripts/generate-eval-samples.py
```

---

## 2. 指标（计划）

| 指标 | 定义（MVP） |
|------|-------------|
| **Pitch sequence accuracy** | GT `extra.eval.pitch_sequence` 与识别旋律音高序列的匹配率（建议 LCS 或 exact） |
| **Measure count error** | \|pred_bars − gt_bars\| |
| **Key / time exact** | 字符串全等（可选权重） |

初始目标（清晰印刷子集）：

- 音高序列 top-line 正确率 **≥ 60%**（跑通后填入实测）

---

## 3. 校验命令（当前可用）

```powershell
# 校验 ready 条目的图片 + GT Score schema
python scripts/eval-accuracy.py --manifest-only

# 打印 GT 统计
python scripts/eval-accuracy.py --gt-stats
```

> 完整「OCR 识别 vs GT」对比将在 M01–M05 补齐后扩展同一脚本。

---

## 4. 当前基线数字

| 引擎 | 子集 | Pitch acc | Measure err | 日期 | 备注 |
|------|------|-----------|-------------|------|------|
| — | — | *TBD* | *TBD* | — | 待首次全量跑分 |

---

## 5. 手动 5 张曲谱

见 [`samples/eval/manual/README.md`](../samples/eval/manual/README.md)。

注意版权：未授权商业谱面勿 push 公开仓库；可用 `samples/private/` 本机评测。

---

## 6. 相关

- ROADMAP P1-7 / Issue #29  
- Schema：`docs/jianpu-schema.md`  
- 样例总览：`samples/README.md`  
