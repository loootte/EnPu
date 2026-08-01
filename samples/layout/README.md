# Layout training samples（L1–L3）

标准见 [docs/train/l1-l3-data-spec.md](../../docs/train/l1-l3-data-spec.md)。

## 目录

每个样本一个子目录：

```text
samples/layout/<id>/
  layout.json
  image.png
```

## 从恩谱工程导出

```powershell
# 仓库根目录
$env:PYTHONPATH = ".\core"
python scripts/export_layout_gt.py `
  --project "C:\path\to\song.enpu.json" `
  --out samples/layout/L00x_name
```

工程格式为桌面 **`.enpu.json`**（`project_version` 0.2，含 `structure` + 可选嵌入图）。

## 本仓库样例

| ID | 来源 | 说明 |
|----|------|------|
| `L001_zuozai_baozuo` | 真实工程《坐在宝座上圣洁羔羊A调》 | M04 页；L2=6 行，每行 4 节 → 3 interior splits |

私有/未授权谱请放 `samples/private/layout/`（勿提交）。
