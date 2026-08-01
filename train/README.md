# EnPu Train — L1–L3 布局训练 Framework（#95）

独立于 `desktop/` 的训练应用：读 **layout data-spec** 样本，训练轻量 **L2 + L3** 模型（#94 MVP-1），导出权重。

| 文档 | 链接 |
|------|------|
| 数据规范 #93 | [docs/train/l1-l3-data-spec.md](../docs/train/l1-l3-data-spec.md) |
| 模型方案 #94 | [docs/train/l1-l3-model-design.md](../docs/train/l1-l3-model-design.md) |
| 样例数据 | [samples/layout/](../samples/layout/) |

## 目录

```text
train/
  README.md
  requirements.txt
  configs/mvp_l2_l3.yaml
  enpu_train/
    data/       # Dataset + 合成样本
    models/     # L2 page y-heat + L3 row x-heat
    losses/
    metrics/    # L2 IoU + L3 split count / mean_abs_x
    engine/     # train / eval
    export/     # state_dict + ONNX
    viz.py
  scripts/
    train.py
    eval.py
    viz_sample.py
    export_from_enpu_project.py
  tests/
```

## 环境

```powershell
cd train
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

需要 **Python 3.10+**、**PyTorch**。有 GPU 时可在配置里设 `train.device: cuda`。

## 数据准备

1. **真实工程** → layout 样本（#93）：

```powershell
# 仓库根
$env:PYTHONPATH = ".\core"
python scripts\export_layout_gt.py --project path\to\song.enpu.json --out samples\layout\L00x

# 或在 train/ 下
python scripts\export_from_enpu_project.py -p path\to\song.enpu.json -o ..\samples\layout\L00x
```

2. **仓库已有**：`samples/layout/L001_zuozai_baozuo/`  
3. **合成**：`train.py` 会按配置自动生成 `data_cache/synth/S00*`（默认 8 张）

抽查可视化：

```powershell
cd train
python scripts\viz_sample.py ..\samples\layout\L001_zuozai_baozuo
```

## 一条命令 toy 训练

```powershell
cd train
python scripts\train.py --config configs\mvp_l2_l3.yaml
```

默认：CPU、3 epoch、真实 layout + 合成数据、写出：

- `runs/mvp_l2_l3/last.pt` / `best.pt`
- `runs/mvp_l2_l3/history.json`
- `runs/mvp_l2_l3/export/layout_net.pt`
- `runs/mvp_l2_l3/export/onnx/*.onnx`（若 ONNX 导出可用）

评估：

```powershell
python scripts\eval.py --ckpt runs\mvp_l2_l3\best.pt --data ..\samples\layout
```

指标：`l2_mean_iou`、`l3_mean_abs_x_error`、`l3_split_count_mae` / `exact`（与 #86 线级语义同构）。

## 模型与 structure 对应

| 模型输出 | 恩谱 structure / IR |
|----------|---------------------|
| L2 1D y 热力峰值 → 水平条带框 | `items[]` layer=L2 `kind=system`；`StaffSystem.rect` |
| L3 行 crop 上 x 热力峰值 | `barlines[]` / `StaffSystem.splits`（interior x） |
| 后处理 `normalize_splits` + `splits_to_measures` | L3 `measure_derived` 框（派生，非主学） |

**core 如何加载（P2 草图，本仓库尚未接插件）：**

1. 读 `export/layout_net.pt` 或 ONNX  
2. 全图 → L2 峰值 → systems  
3. 每行 crop → L3 峰值 → splits（全图 x）  
4. 填入 `StructureDebug` / `PageLayout`，再跑现有 L4–L5 或仅叠图  
5. 配置预留：`ENPU_STRUCTURE_ENGINE=learned_l1l3`（实现见后续 Issue）

规则几何管线保持 fallback。

## 测试

```powershell
cd train
python -m pytest tests -q
```

## 非目标

- 大规模真实集 / 完整合成流水线  
- core 内完整 `learned_l1l3` 推理插件  
- 精度超过几何基线的承诺  

父任务：[Issue #92](https://github.com/loootte/EnPu/issues/92) · 本任务 [#95](https://github.com/loootte/EnPu/issues/95)
