# Core 加载 L1–L3 训练权重（#104）

> 将 `train/` 导出的布局权重接入 `core` structure 管线；默认仍为几何 **rule**。

## 配置（环境变量，`ENPU_` 前缀）

| 变量 | 默认 | 说明 |
|------|------|------|
| `ENPU_PIPELINE_MODE` | `legacy` | 设为 `structure` 才走 L1–L5 |
| `ENPU_STRUCTURE_L1L3_ENGINE` | `rule` | `rule` \| `learned` |
| `ENPU_L1L3_WEIGHTS` | _(空)_ | `layout_net.pt` / `best.pt` / `last.pt` 路径 |
| `ENPU_L1L3_DEVICE` | `cpu` | `cpu` 或 `cuda` |
| `ENPU_L1L3_FALLBACK` | `rule` | 加载/推理失败时：`rule` 或 `none`（抛错） |

Settings 字段：`structure_l1l3_engine`、`l1l3_weights`、`l1l3_device`、`l1l3_fallback`。

## 权重格式

与训练导出一致：

1. **`enpu_layout_net_v0`**（`train` `export_state_dict`）  
   - `format`, `model` (state_dict), `tasks`, `l2_heat_len`, `l3_heat_len`  
2. **训练 ckpt**（`best.pt` / `last.pt`）  
   - `model` + `cfg`（含 `page_h/w`, `row_h/w`, heat 长度等）

Core **不** import `train/` 包；网络结构在 `core/app/pipeline/structure/learned/model.py` 与训练侧对齐。

## 行为

```text
structure recognize
  L1: 规则版面（title / key_time / score）
  L2+L3:
    engine=rule    → 现有 OpenCV 谱行 + 分割线
    engine=learned → LayoutNet 热力 → systems + splits
                     → normalize_splits / splits_to_measures
  L4–L5: 不变（几何 ROI + OCR）
```

- 坐标：全图像素，与 data-spec / 桌面一致。  
- `meta.parse_warnings` / `preprocess_steps` 含 `l1l3=learned|rule` 与 fallback 信息。  
- 权重缺失、torch 未装、推理异常 → 默认 **fallback rule**（可观察 warning）。

## 依赖策略

| 场景 | 依赖 |
|------|------|
| 默认 core / **CI** / 精简安装包 | **不需要** torch；`engine=rule` |
| 本机 learned 推理 | `pip install torch`（与训练环境可共用） |
| Windows 默认 NSIS 包 | **不**捆绑 torch；仅 rule |

- `core/requirements-ci.txt` **不得**加入 torch。  
- `structure/learned` 在 **import 时不强制加载 torch**（懒加载）；仅 `load_layout_weights` / `run_learned_l2_l3` 需要。  
- 无 torch 时设 `ENPU_STRUCTURE_L1L3_ENGINE=learned` 会 **fallback 到 rule**（默认 `ENPU_L1L3_FALLBACK=rule`）。

## 使用示例

```powershell
cd D:\workspace\EnPu
$env:PYTHONPATH = ".\core"
$env:ENPU_PIPELINE_MODE = "structure"
$env:ENPU_RECOGNIZE_ENGINE = "mock"   # 或 paddleocr
$env:ENPU_STRUCTURE_L1L3_ENGINE = "learned"
$env:ENPU_L1L3_WEIGHTS = ".\train\runs\mvp_l2_l3\best.pt"
$env:ENPU_L1L3_DEVICE = "cpu"

# 启动 core 后 POST /v1/recognize
# 或对比脚本：
python scripts\eval_l1l3_engines.py --data samples\layout --weights train\runs\mvp_l2_l3\best.pt --out reports\l1l3_engines.json
```

## 模块路径

```text
core/app/pipeline/structure/learned/
  model.py        # LayoutNet
  loader.py       # 权重加载与缓存
  postprocess.py  # 热力 → 框 / split x
  adapter.py      # → PageLayout / splits 规范化
  infer_l1l3.py   # 端到端 L2+L3
pipeline.py       # engine 分支 + fallback
```

## 限制

- MVP 模型仅 **L2+L3 热力**；L1 仍为规则（hybrid）。  
- 不承诺 learned 全面超过 rule；先接入与可评测。  
- 无 L4–L5 学习模型。  
- 训练 UI / Framework 与 core 仅通过 **权重文件** 交换。

## 相关

- #104 本能力 · #95 训练 Framework · #101 训练 UI · #93 data-spec · #94 模型方案  
- [l1-l3-model-design.md](./l1-l3-model-design.md) · [l1-l3-data-spec.md](./l1-l3-data-spec.md)  
