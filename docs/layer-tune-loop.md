# 单层参数自动调优闭环（Issue #89）

> 识别 → 手动框 GT → 评估 → 自动调参 → 再识别（仅本层）

## 工作流

```text
1. 识别曲谱（structure）
2. 编辑模式修正 L3（或 L4）框 →「将编辑框存为标注」
3. 评估（对比自动框 / 当前结果）
4. 「本层自动调优」→ 随机/网格搜索本层参数，最小化 layer loss
5. 「应用最优并再识别」→ 写回 runtime 参数，重跑该层及下游
6. （可选）继续改框 → 新 GT → 再调优
```

## 目标函数（单层）

```text
loss = w_iou*(1 - mean_IoU)
     + w_cnt * |n_pred - n_gt| / n_gt
     + w_fn  * fn_rate
     + w_fp  * fp_rate
```

仅使用**当前层** pred vs GT，不用下游 Pitch F1 反传。

## 配置

| 文件 | 说明 |
|------|------|
| `configs/tune/default_params.yaml` | L3/L4 默认阈值 |
| `configs/tune/space_l3.yaml` | L3 搜索空间 + 目标权重 |
| `configs/tune/space_l4.yaml` | L4 搜索空间 |

代码从 `app.tuning.params` 读取 runtime 覆盖；调参成功后可 `apply_best` 写回。

## CLI

```powershell
core\.venv\Scripts\python.exe scripts\tune_layer.py `
  --image samples/eval/images/E01_print_c_4_4_grace_demo.png `
  --gt path/to/edit-gt.json `
  --layer l3 --trials 40 --seed 42 --method random --apply `
  --out reports/tune_l3.trials.jsonl
```

## API

- `POST /v1/evaluation/tune-layer` / `tune-layer/upload`
- `POST /v1/evaluation/params/apply` · `params/reset` · `GET /params`

## Desktop

侧栏 **分层精度评测**：

1. 将编辑框存为标注  
2. **本层自动调优 (L3)**  
3. **应用最优参数**（下一轮识别会使用）  
4. 用结构层「按 L2 框重识别下层」刷新预测  

## 注意

- 单页 GT 易过拟合；多页 GT 聚合后续再做  
- 相同 `seed` + trials 设置应可复现 best  
- GT 在调优过程中**不会被修改**  
