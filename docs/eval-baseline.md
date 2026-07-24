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
| `manual_real` | 5 | 从 Documents 的 `.jianpu`+`.pdf` 导入（见下） |

生成合成集 + 导入手动 5 张：

```powershell
cd D:\workspace\EnPu
python scripts/generate-eval-samples.py
pip install pymupdf   # PDF → PNG
python scripts/import-manual-scores.py --docs-dir "$env:USERPROFILE\Documents"
python scripts/eval-accuracy.py --manifest-only   # 使用 manifest.local.json
```

手动映射（M01–M05）：

| ID | 曲目 |
|----|------|
| M01 | Fur Elise |
| M02 | 卡农 Canon in D |
| M03 | 预备雨露甘霖 |
| M04 | 坐在宝座上圣洁羔羊 A调 |
| M05 | 坐在宝座上圣洁羔羊 C调 |

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

## 4. 当前基线数字（PaddleOCR）

复现：

```powershell
cd D:\workspace\EnPu
# 需已 import 手动样例 → samples/eval/manifest.local.json
core\.venv\Scripts\python.exe scripts/eval-accuracy.py --run --engine paddleocr
# 报告: samples/eval/reports/baseline-paddleocr.json
```

**指标说明**

- **Pitch F1**：GT 与预测音高序列的 token LCS，再算 precision/recall/F1  
- **weighted F1**：按 GT 音高总数加权汇总  
- **key/time**：识别 Score 的调号/拍号字符串全等  
- **\|Δbars\|**：预测小节数与 GT 小节数绝对差  

### 2026-07-24 全量 20 张（engine=paddleocr）

| 子集 | n | Pitch F1 (avg) | Pitch F1 (weighted) | Pitch Recall (avg) | Key | Time | mean \|Δbars\| |
|------|---|----------------|---------------------|--------------------|-----|------|----------------|
| **ALL** | 20 | 71.7% | **74.2%** | 94.2% | 100% | 100% | 7.6 |
| print_clear | 10 | 69.8% | **69.4%** | 100% | 100% | 100% | 1.9 |
| scan_like | 3 | 65.8% | 65.9% | 100% | 100% | 100% | 2.0 |
| cn_lyrics | 2 | 63.1% | 63.0% | 100% | 100% | 100% | 1.0 |
| manual_real | 5 | 82.4% | **75.7%** | 77.0% | 100% | 100% | 25.0 |

**print_clear weighted pitch F1 = 69.4% → PASS（目标 ≥60%）**

### 手动 5 张明细

| ID | 曲目 | GT 音高数 | Pred | F1 | Recall | \|Δbars\| |
|----|------|-----------|------|-----|--------|-----------|
| M01 | Fur Elise | 616 | 359 | 63.4% | 50.2% | 29 |
| M02 | 卡农 Canon in D | 175 | 144 | 89.0% | 81.1% | 1 |
| M03 | 预备雨露甘霖 | 138 | 130 | 91.0% | 88.4% | 35 |
| M04 | 坐在宝座上圣洁羔羊 A | 106 | 103 | 85.2% | 84.0% | 32 |
| M05 | 坐在宝座上圣洁羔羊 C | 106 | 100 | 83.5% | 81.1% | 28 |

### 观察

1. **合成 print_clear**：Recall 很高（数字几乎都扫到），但 Pred 音高偏多 → Precision 拉低 F1（OCR 把标题/歌词里的数字或重复行算进音高流）。  
2. **真实曲谱**：卡农/诗歌 F1 约 83–91%；Fur Elise 最长、最密（十六分音），Recall 仅 ~50%。  
3. **小节数**：合成谱平均差 ~2 小节；真实谱差较大（反复/多行/OCR 丢 `|`）。调号与拍号在本批 **全部命中**（与 GT / 元数据提示有关，解读时注意）。  
4. 报告 JSON：`samples/eval/reports/baseline-paddleocr.json`（本地生成，可不入库）。  

---

## 5. 手动 5 张曲谱

见 [`samples/eval/manual/README.md`](../samples/eval/manual/README.md)。

注意版权：未授权商业谱面勿 push 公开仓库；可用 `samples/private/` 本机评测。

---

## 6. 相关

- ROADMAP P1-7 / Issue #29  
- Schema：`docs/jianpu-schema.md`  
- 样例总览：`samples/README.md`  
