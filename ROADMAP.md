# EnPu（恩谱）产品与技术路线图

> **中文敬拜简谱 OMR 数字化工具**  
> 把扫描/拍照的中文敬拜简谱识别成可编辑、可播放、可导出的数字化乐谱，服务教会敬拜团队。  
> 目标格式：MusicXML / MIDI / 自定义 JSON。

**仓库**：https://github.com/loootte/EnPu  
**最后更新**：2026-07-24  
**当前阶段**：Phase 1 主路径 + 准确率基线已通（#29）；下一阶段 **结构精度**（#34–#38）与 **v0.1.0**；云端 #13 可并行  

---

## 1. 产品愿景

| 角色 | 核心诉求 |
|------|----------|
| 敬拜主领 / 乐手 | 快速把纸质简谱变成可改调、可播放的数字谱 |
| 诗歌管理同工 | 建立教会诗歌库，统一格式便于检索与分享 |
| 琴师 / 编曲 | 导出 MIDI / MusicXML 到其他 DAW 或记谱软件 |

**成功定义（长期）**

1. 手机拍照或扫描 PDF 后，几分钟内得到可编辑简谱  
2. 支持常见中文敬拜简谱版式（数字音符、拍号、调号、歌词、反复记号等）  
3. 桌面端可离线使用；可选云端加速/批量处理  
4. 导出 MusicXML / MIDI / EnPu JSON，可回流到主流乐谱工具  

---

## 2. 已确定技术路线

| 层级 | 选型 | 说明 |
|------|------|------|
| 桌面 UI | **Tauri 2 + React + TypeScript + Tailwind** | 轻量、可打包 Windows 安装包 |
| 识别核心 | **Python + FastAPI** | 独立服务，便于本地 sidecar 与云端复用 |
| 图像处理 | **OpenCV** | 矫正、二值化、谱线/区域分割 |
| 文字/数字 OCR | **PaddleOCR** | 中文与数字效果较好，适合简谱数字与歌词 |
| 乐谱结构化 | **music21** | 生成 MusicXML / MIDI |
| 本地集成 | **PyInstaller sidecar** | 桌面端随应用启动本地识别服务 |
| 云端部署 | **同一套 FastAPI + Docker** | 桌面端可切换「本地 / 云端」 |

**架构原则**

```
┌─────────────────────────────┐
│  Tauri Desktop (React UI)   │
│  - 导入图片 / 预览 / 编辑    │
│  - 本地 or 云端 模式切换     │
└──────────────┬──────────────┘
               │ HTTP (localhost or remote)
               ▼
┌─────────────────────────────┐
│  FastAPI OMR Core           │
│  OpenCV → PaddleOCR → 规则/ │
│  模型结构化 → music21       │
└─────────────────────────────┘
```

**流水线（当前）**

`图像 → OpenCV 预处理 → PaddleOCR → 规则解析 → Score JSON → music21`

**核心判断（#33 / 基线结论）**：**短板不在 OCR 引擎，而在版面理解与后处理**（非谱行数字、小节划分、高密度时值）。

---

## 3. 阶段总览

| 阶段 | 名称 | 目标时长（估算） | 优先级 | 状态 |
|------|------|------------------|--------|------|
| **Phase 0** | **桌面端 PoC** | **2–3 周** | **P0** | **✅ 完成（M1）** |
| Phase 1 | 识别核心 MVP | 4–6 周 | P0 | ✅ 主路径完成；基线 ✅ #29 |
| Phase 2 | 编辑、播放与导出 | 3–4 周 | P1 | ✅ **#12 MVP** |
| Phase 3 | 云端双模式与部署 | 2–3 周 | P1 | 待开始（#13） |
| Phase 4 | 精度、体验与发布 | 4–6 周 | P0 | 🔄 打包 ✅ #14；**精度攻坚中** #34–#38 |

> 时间估算按 **1 名全栈 + 兼职算法** 节奏；可按人力压缩或拉长。

---

## 4. 准确率基线结论（#29 → #33）

详见 [`docs/eval-baseline.md`](./docs/eval-baseline.md)。PaddleOCR 全量 20 张（2026-07-24）：

| 子集 | weighted Pitch F1 | 备注 |
|------|-------------------|------|
| print_clear | **69.4%** | ✅ 达到 ≥60% 验收线 |
| ALL | **74.2%** | |
| manual_real（真实谱） | **75.7%**（avg F1 82.4%） | 敬拜谱约 83–91%；Fur Elise ~63% |
| 调号 / 拍号 | **100%**（本批） | 后续需与元数据提示解耦，防虚高 |

**主要短板**

1. 标题/歌词数字污染音高序列 → Precision 偏低  
2. 真实谱小节划分差（mean \|Δbars\| ≈ 25）  
3. 高密度谱 Recall 偏低（Fur Elise ≈ 50%）  

**产品含义**：闭环已可用；下一优先级是 **结构正确 + 真实敬拜场景**，而非更换 OCR 引擎。

---

## Phase 0 — 桌面端 PoC（Milestone 1）

**状态**：✅ 完成（#1–#8）

### 0.3 验收标准（Definition of Done）

1. 在干净的 Windows 开发机上，按文档可在 **30 分钟内** 启动 UI + 核心服务  
2. 导入仓库提供的 **至少 1 张样例简谱图**，点击识别后 **60 秒内** 返回结果  
3. 界面可见：原图预览 + 识别输出（至少含 OCR 文本列表或 JSON）  
4. 识别失败时有明确错误提示（服务未启动、文件格式不支持等）  
5. 核心接口有简单 OpenAPI/Swagger 可访问（FastAPI 自带）  
6. **不要求**：调号/拍号准确、MusicXML 正确、播放、安装包精修  

---

## Phase 1 — 识别核心 MVP

**优先级**：P0  
**状态**：✅ 主路径完成；评测基线 ✅  

### 1.2 主要任务

| ID | 任务 | 优先级 | 状态 |
|----|------|--------|------|
| P1-1 | 简谱版式调研与标注规范 | P0 | ✅ `docs/jianpu-schema.md` |
| P1-2 | 图像流水线增强：倾斜矫正、去噪、谱表区域检测 | P0 | 部分；**区域检测升级见 #34** |
| P1-3 | OCR → 音高+时值 → `Score` | P0 | ✅ **#10**（含小节线 CV 恢复） |
| P1-4 | 歌词行与音符行对齐策略 | P1 | 🔄 MVP zip；精细对齐待做 |
| P1-5 | EnPu JSON Schema v0.1 | P0 | ✅ **#9** |
| P1-6 | music21 导出 MusicXML / MIDI | P1 | ✅ **#11** |
| P1-7 | 评测集 + 准确率指标脚本 | P1 | ✅ **#29**（合成 15 + 手动导入 + 基线报告） |
| P1-8 | API 版本化、错误码、超时与日志 | P1 | 部分（v1 API） |

### 1.3 验收标准

1. 内部 JSON：调号、拍号、旋律音高与基础时值 → **✅**  
2. print_clear 音高序列基线 ≥60% → **✅ 69.4% weighted F1**（#29）  
3. 可导出 MuseScore 可开 MusicXML → **✅ #11**  
4. API 文档 / Schema → **进行中**  

---

## Phase 2 — 编辑、播放与导出

**状态**：✅ MVP（#12）

| ID | 任务 | 状态 |
|----|------|------|
| P2-1 | 简谱结果编辑 UI | ✅ |
| P2-2 | WebAudio 试听 | ✅ |
| P2-3 | 导出 MusicXML / MIDI / JSON | ✅ |
| P2-4 | `.enpu.json` 工程 | ✅ |
| P2-5 | 批处理多页 | ⬜ |

---

## Phase 3 — 云端双模式与部署

**状态**：待开始 · **#13**（可与精度并行，不阻塞 v0.1.0）

---

## Phase 4 — 精度、体验与正式发布

**优先级**：P0（精度） / P1（发布打磨）  
**依赖**：Phase 1 基线 + Phase 2 闭环  

### 4.1 目标

1. 结构精度：非谱行过滤、小节划分、真实敬拜谱可用  
2. Windows 安装包可分发；基线数字可引用  
3. v0.1.0 公开发布  

### 4.2 主要任务

| ID | 任务 | 优先级 | 状态 |
|----|------|--------|------|
| P4-A | 版面/谱行分类，过滤非谱行数字 | P0 | 🔄 **#34**（layout 门控已合入分支） |
| P4-B | 小节线检测与切分加固 | P0 | ⬜ **#35** |
| P4-C | 扩充真实敬拜谱评测集（≥15） | P0 | ⬜ **#36** |
| P4-D | 高密度谱与时值线检测 | P1 | ⬜ **#37** |
| P4-E | print_clear F1 门槛进 CI | P1 | 🔄 **#38**（`ci.yml` eval-print-clear job） |
| P4-1 | 拍照场景增强 | P1 | 待做 |
| P4-2 | 反复/倚音/连音等结构扩展 | P2 | 待做 |
| P4-3 | Sidecar + Tauri 打包流水线 | P0 | ✅ **#14** + CD Windows |
| P4-4 | 崩溃上报/性能/体积 | P2 | 待做 |
| P4-5 | 用户文档、快捷键、样例库 | P1 | 部分 |
| P4-6 | **v0.1.0** 公开发布 | P0 | 🔄 流水线就绪；待精度最小集 + tag |

### 4.3 验收导向（精度 + 发布）

| 项 | 目标方向 |
|----|----------|
| print_clear weighted Pitch F1 | 维持 **≥60%**，尽量提升 Precision |
| 真实敬拜谱 Pitch F1 | 保持/提升当前 **80%+** 水平 |
| 真实谱 mean \|Δbars\| | 从 ~25 **明显下降**（阶段性目标如均值 &lt;5 或按曲目长度归一化） |
| 评测集 | 真实敬拜谱 **≥15** 张，可复现脚本与报告 |
| v0.1.0 | Windows 安装包 + 公开基线报告 + 主闭环可用 |

### 4.4 技术优先级（实现顺序建议）

```text
P0  #34 非谱行过滤  ──►  #35 小节划分  ──►  #36 真实评测集
P1  #37 高密度时值     #38 CI 门槛
P1  v0.1.0 tag（安装包 + 基线可引用）
P2  拍照鲁棒 / 复杂符号 / Phase 3 云端
```

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 简谱版式不统一 | 规则解析脆弱 | 先锁定常见模板；Schema 预留扩展；真实评测集驱动 |
| 标题数字污染 | Precision/F1 虚低 | #34 区域门控 |
| 小节线 OCR 丢失 | 结构不可用 | #35 几何检测 + 拍号软切分 |
| Paddle 体积大 | 安装包与冷启动 | 默认 mock sidecar；Paddle 按需安装脚本 |
| music21 语义差 | 导出不准 | JSON 为真相源 |
| 样本版权 | 测试数据受限 | 合成 CC0 + 授权/本地 private；公域古典可入库（M01/M02） |

---

## 6. 里程碑检查点

| 里程碑 | 标志性交付 | 状态 |
|--------|------------|------|
| **M1 — Desktop PoC** | Windows 可运行；导入图 → 本地识别 → UI 展示 | ✅ |
| **M2 — OMR MVP** | 结构化 JSON + MusicXML + 准确率基线 | ✅ |
| **M2.5 — 结构可用** | 非谱行过滤 + 小节划分改善 + 真实评测 | 🔄 #34–#36 |
| M3 — 可用闭环 | 编辑 + 试听 + 导出 | ✅ MVP |
| M4 — 双模式 | 本地/云端切换 | ⬜ #13 |
| **M5 — v0.1 发布** | 安装包 + 文档 + 基线 + Release | 🔄 |

---

## 7. Issue 拆分索引

Issues 列表：https://github.com/loootte/EnPu/issues

| # | 标题 | 阶段 | 状态 |
|---|------|------|------|
| [#1](https://github.com/loootte/EnPu/issues/1)–[#8](https://github.com/loootte/EnPu/issues/8) | Phase 0 PoC | P0 | ✅ |
| [#9](https://github.com/loootte/EnPu/issues/9)–[#11](https://github.com/loootte/EnPu/issues/11) | Schema / 解析 / 导出 | P1 | ✅ |
| [#12](https://github.com/loootte/EnPu/issues/12) | 编辑试听导出 UI | P2 | ✅ |
| [#13](https://github.com/loootte/EnPu/issues/13) | Docker 与本地/云端切换 | P3 | ⬜ |
| [#14](https://github.com/loootte/EnPu/issues/14) | Windows 安装包与 sidecar | P4 | ✅ |
| [#29](https://github.com/loootte/EnPu/issues/29) | 准确率基准线与评测集 | P1 | ✅ 基线已测 |
| [#33](https://github.com/loootte/EnPu/issues/33) | 基于基线更新产品与技术路线 | docs | ✅ 本文档 |
| [#34](https://github.com/loootte/EnPu/issues/34) | 版面/谱行分类，过滤非谱行数字 | P4 | ⬜ **下一步** |
| [#35](https://github.com/loootte/EnPu/issues/35) | 小节线检测与切分加固 | P4 | ⬜ |
| [#36](https://github.com/loootte/EnPu/issues/36) | 扩充真实敬拜谱评测集 | P4 | ⬜ |
| [#37](https://github.com/loootte/EnPu/issues/37) | 高密度谱与时值线检测 | P4 | ⬜ |
| [#38](https://github.com/loootte/EnPu/issues/38) | print_clear F1 CI 门槛 | P1 | 🔄 `ci.yml` 已加 gate |

---

## 8. 贡献与决策记录

| 日期 | 决策 |
|------|------|
| 2026-07-23 | 技术栈 Tauri2/React + FastAPI/OpenCV/PaddleOCR/music21 |
| 2026-07-23 | Phase 0 / M1 完成（#1–#8） |
| 2026-07-24 | Schema/解析/导出/UI/打包（#9–#14、#12） |
| 2026-07-24 | **#29** 基线：print_clear F1 69.4% PASS；真实敬拜谱 ~80%+ |
| 2026-07-24 | **#33** 转向结构精度：#34 过滤 → #35 小节 → #36 真实集；v0.1.0 不阻塞于云端 |

### Phase 摘要

**Phase 0–2**：PoC、识别 MVP、编辑导出、打包 CD 已通。  

**Phase 1 收尾**：评测与基线完成（#29）。  

**下一迭代（建议）**

| 优先级 | Issue | 说明 |
|--------|-------|------|
| P0 | **[#34](https://github.com/loootte/EnPu/issues/34)** | 非谱行数字过滤 |
| P0 | [#35](https://github.com/loootte/EnPu/issues/35) | 小节划分 |
| P0 | [#36](https://github.com/loootte/EnPu/issues/36) | 真实敬拜评测集 |
| P1 | [#37](https://github.com/loootte/EnPu/issues/37) / [#38](https://github.com/loootte/EnPu/issues/38) | 密度时值 / CI 门槛 |
| P1 | v0.1.0 | 安装包 + 基线报告 tag |
| P2 | [#13](https://github.com/loootte/EnPu/issues/13) | 云端 |

---

*本文档随 #33 按 eval-baseline 更新；精度任务以 #34–#38 为执行单元。*
