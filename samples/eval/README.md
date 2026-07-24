# Eval 评测集（Issue #29）

| 项 | 数量 | 状态 |
|----|------|------|
| 合成曲谱 `E01`–`E15` | 15 | ✅ 已生成（CC0） |
| 手动真实曲谱 `M01`–`M05` | 5 | ⬜ 见 [manual/README.md](./manual/README.md) |
| **合计目标** | **20** | 进行中 |

## 目录

| 路径 | 说明 |
|------|------|
| `manifest.json` | 全量索引 |
| `images/` | 合成 PNG |
| `gt/` | Ground-truth Score JSON |
| `manual/` | 你手动加入的 5 张 |

## 再生合成集

```powershell
python scripts/generate-eval-samples.py
python scripts/eval-accuracy.py --manifest-only
```

文档：[docs/eval-baseline.md](../../docs/eval-baseline.md)
