# 手动评测样例（M01–M05）

此目录留给**你正在使用的真实曲谱**（Issue #29 目标 20 张：合成 15 + 手动 5）。

## 一键导入（推荐）

从 `%USERPROFILE%\Documents` 读取同名 `.jianpu` + `.pdf`：

| ID | 数字化 (.jianpu) | 待识别 (PDF→PNG) |
|----|------------------|------------------|
| M01 | Fur Elise.jianpu | Fur Elise.pdf |
| M02 | 卡农 Canon in D.jianpu | 卡农 Canon in D.pdf |
| M03 | 预备雨露甘霖.jianpu | 预备雨露甘霖.pdf |
| M04 | 坐在宝座上圣洁羔羊 A调.jianpu | 同名 PDF |
| M05 | 坐在宝座上圣洁羔羊 C调.jianpu | 同名 PDF |

```powershell
# 需: pip install pymupdf
cd D:\workspace\EnPu
python scripts/import-manual-scores.py --docs-dir "$env:USERPROFILE\Documents"

# 校验（自动优先用 manifest.local.json）
python scripts/eval-accuracy.py --manifest-only
python scripts/eval-accuracy.py --gt-stats
```

生成内容（**默认 gitignore，勿公开 push 未授权谱面**）：

- `M0N_manual.png` — PDF 首页渲染（多页另有 `_p2.png`…）
- `M0N_manual.gt.json` — 由 `.jianpu` 转为 EnPu Score v0.1
- `M0N_manual.source.jianpu` — 源文件副本
- `../manifest.local.json` — 含 20 条 ready 的本地索引

## 手动放置约定

对每个样例 `N`（1–5）：

| 文件 | 说明 |
|------|------|
| `M0N_manual.png`（或 `.jpg`） | 曲谱图片 |
| `M0N_manual.gt.json` | Ground-truth EnPu Score v0.1 |

## Ground-truth 最小要求

`M0N_manual.gt.json` 至少包含：

```json
{
  "schema_version": "0.1",
  "title": "你的曲名（可匿名）",
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
            { "pitch": "1", "octave": 0, "duration": "quarter", "dots": 0, "is_rest": false }
          ]
        }
      ]
    }
  ],
  "extra": {
    "eval": {
      "id": "M01_manual",
      "subset": "manual_real",
      "pitch_sequence": ["1", "2", "3"],
      "measure_count": 1,
      "synthetic": false,
      "license": "user-authorized-internal-only"
    }
  }
}
```

可用仓库 `samples/scores/example-minimal.json` 或 `samples/eval/gt/E01_*.json` 作模板。

## 版权

- **不要**把未授权的商业诗歌扫描件 push 到公开仓库。  
- 若仅本机评测：可放在 `samples/private/`（gitignore）并本地改 manifest。  
- 若可公开：在 PR 中注明授权（自制 / 已获授权 / 公有领域）。

## 校验

```powershell
# 校验 GT 是否符合 Score schema
cd core
.\.venv\Scripts\python.exe ..\scripts\eval-accuracy.py --manifest-only
```
