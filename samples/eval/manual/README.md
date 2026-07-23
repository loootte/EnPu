# 手动评测样例（M01–M05）

此目录留给**你正在使用的真实曲谱**（Issue #29 目标 20 张：合成 15 + 手动 5）。

## 放置约定

对每个样例 `N`（1–5）：

| 文件 | 说明 |
|------|------|
| `M0N_manual.png`（或 `.jpg`） | 曲谱图片 |
| `M0N_manual.gt.json` | Ground-truth EnPu Score v0.1 |

建议同时在 `../manifest.json` 中把对应条目的 `status` 从 `pending_user` 改为 `ready`，并填入 `key` / `time_signature` / `pitch_sequence` / `measure_count`。

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
