# EnPu（恩谱）产品与技术路线图

> **中文敬拜简谱 OMR 数字化工具**  
> 把扫描/拍照的中文敬拜简谱识别成可编辑、可播放、可导出的数字化乐谱，服务教会敬拜团队。  
> 目标格式：MusicXML / MIDI / 自定义 JSON。

**仓库**：https://github.com/loootte/EnPu  
**最后更新**：2026-07-24  
**当前阶段**：Phase 2 — 编辑 / 试听 / 导出 UI MVP（#12）；Phase 1 核心导出已通，评测集待做

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

---

## 3. 阶段总览

| 阶段 | 名称 | 目标时长（估算） | 优先级 | 状态 |
|------|------|------------------|--------|------|
| **Phase 0** | **桌面端 PoC** | **2–3 周** | **P0** | **✅ 完成（M1）** |
| Phase 1 | 识别核心 MVP | 4–6 周 | P0 | 🔄 核心路径完成；评测集待做 |
| Phase 2 | 编辑、播放与导出 | 3–4 周 | P1 | 🔄 **#12 MVP 进行中** |
| Phase 3 | 云端双模式与部署 | 2–3 周 | P1 | 待开始 |
| Phase 4 | 精度、体验与发布 | 4–6 周 | P2 | 待开始 |

> 时间估算按 **1 名全栈 + 兼职算法** 节奏；可按人力压缩或拉长。

---

## Phase 0 — 桌面端 PoC（Milestone 1）

**优先级**：P0（最高）  
**时长估算**：2–3 周  
**目标**：在 Windows 上跑通「可安装/可运行的桌面程序 + 导入图片 + 本地 Python 核心基础识别 + 界面展示结果」，**证明技术路线可行**。不要求识别精度。

### 0.1 目标

- [ ] Windows 上可启动的 Tauri 2 桌面应用  
- [ ] 用户可导入一张简谱图片（png/jpg）  
- [ ] 本地 Python FastAPI 服务完成一次「基础识别」流水线  
- [ ] UI 展示识别结果（原始 OCR 文本、JSON 结构或简易可视化均可）  
- [ ] 文档说明如何从零启动开发环境  

### 0.2 主要任务

| ID | 任务 | 优先级 | 标签建议 |
|----|------|--------|----------|
| P0-1 | 仓库脚手架：monorepo 目录、基础 README、开发约定 | P0 | `documentation` |
| P0-2 | Python 核心骨架：FastAPI 健康检查 + `/v1/recognize` 占位接口 | P0 | `core` `poc` |
| P0-3 | 最小识别流水线：读图 → OpenCV 预处理 → PaddleOCR → 返回文本/简单结构 | P0 | `core` `poc` |
| P0-4 | Tauri 2 + React + TS + Tailwind 桌面壳 | P0 | `ui` `poc` |
| P0-5 | UI：导入图片、预览、触发识别、展示结果 | P0 | `ui` `poc` |
| P0-6 | 本地联调：桌面端调用本机 FastAPI（开发态） | P0 | `poc` `core` `ui` |
| P0-7 | （可选）PyInstaller 打本地 sidecar 或一键启动脚本 | P1 | `poc` `core` |
| P0-8 | PoC 验收文档与演示素材（样例简谱图） | P0 | `documentation` `poc` |

### 0.3 验收标准（Definition of Done）

1. 在干净的 Windows 开发机上，按文档可在 **30 分钟内** 启动 UI + 核心服务  
2. 导入仓库提供的 **至少 1 张样例简谱图**，点击识别后 **60 秒内** 返回结果  
3. 界面可见：原图预览 + 识别输出（至少含 OCR 文本列表或 JSON）  
4. 识别失败时有明确错误提示（服务未启动、文件格式不支持等）  
5. 核心接口有简单 OpenAPI/Swagger 可访问（FastAPI 自带）  
6. **不要求**：调号/拍号准确、MusicXML 正确、播放、安装包精修  

### 0.4 明确不做（Out of Scope）

- 高精度结构解析、反复跳跃、复杂多声部  
- 云端部署、账号体系  
- 乐谱编辑器、MIDI 播放  
- macOS / Linux 打包（PoC 仅 Windows）  

---

## Phase 1 — 识别核心 MVP

**优先级**：P0  
**时长估算**：4–6 周  
**依赖**：Phase 0 完成  

### 1.1 目标

在常见「单页、印刷清晰」的中文敬拜简谱上，产出可用的结构化结果（自定义 JSON），并具备初步 MusicXML 导出能力。

### 1.2 主要任务

| ID | 任务 | 优先级 | 状态 |
|----|------|--------|------|
| P1-1 | 简谱版式调研与标注规范（数字、时值、小节线、调号、拍号、歌词） | P0 | ✅ 见 `docs/jianpu-schema.md` |
| P1-2 | 图像流水线增强：倾斜矫正、去噪、谱表区域检测 | P0 | 部分（PoC 预处理）；增强待做 |
| P1-3 | 符号/数字序列解析：OCR → 音高+时值 → `Score` | P0 | ✅ **#10 MVP**（含小节线 CV 恢复） |
| P1-4 | 歌词行与音符行对齐策略 | P1 | 🔄 MVP 简单 zip；精细对齐待做 |
| P1-5 | EnPu 内部 JSON Schema 定稿（v0.1） | P0 | ✅ **#9** |
| P1-6 | music21 导出 MusicXML / MIDI（MVP 子集） | P1 | ✅ **#11 MVP** |
| P1-7 | 评测集：≥20 张样例 + 简单准确率指标脚本 | P1 | 待做（现有 3 张合成样例） |
| P1-8 | 核心 API 版本化、错误码、任务超时与日志 | P1 | 部分（v1 API）；增强待做 |

### 1.3 验收标准

1. 内部 JSON 能描述：调号、拍号、至少一条旋律的音高序列与基础时值 → **✅ Score v0.1 + parse MVP**  
2. 在评测集「清晰印刷」子集上，音高序列 top-line 正确率达到团队约定基线（建议先定 ≥60%，再迭代） → **待评测集**  
3. 可导出可被 MuseScore 打开的 MusicXML（允许缺失装饰音/复杂反复） → **✅ #11**（`POST /v1/export`）  
4. API 文档完整，输入输出有 Schema → **进行中**（`docs/api.md` + OpenAPI）  

---

## Phase 2 — 编辑、播放与导出

**优先级**：P1  
**时长估算**：3–4 周  
**依赖**：Phase 1 的 JSON Schema 与基础识别  

### 2.1 目标

识别结果可人工修正，可试听，可导出常用格式，满足敬拜排练最小闭环。

### 2.2 主要任务

| ID | 任务 | 优先级 | 状态 |
|----|------|--------|------|
| P2-1 | 简谱结果编辑 UI（音符、拍号、调号、歌词） | P0 | ✅ **#12 MVP** |
| P2-2 | 本地 MIDI/合成器试听（WebAudio 或轻量引擎） | P1 | ✅ WebAudio 试听 |
| P2-3 | 导出 MusicXML / MIDI / JSON 文件 | P0 | ✅ UI + `/v1/export` |
| P2-4 | 工程文件保存/打开（EnPu Project） | P1 | ✅ `.enpu.json` MVP |
| P2-5 | 批处理多页（同一首歌多页拼接，MVP） | P2 | 待做 |

### 2.3 验收标准

1. 用户可修改错误音高/歌词并保存 → **✅ 编辑 + 保存工程**  
2. 一键导出三种格式中至少 MusicXML + JSON → **✅ JSON / MusicXML / MIDI**  
3. 可播放主旋律试听（节奏允许近似） → **✅ WebAudio 试听**  

---

## Phase 3 — 云端双模式与部署

**优先级**：P1  
**时长估算**：2–3 周  
**依赖**：Phase 0/1 的 FastAPI 核心稳定  

### 3.1 目标

同一套核心代码支持 Docker 云端部署；桌面端可切换本地/云端识别。

### 3.2 主要任务

| ID | 任务 | 优先级 |
|----|------|--------|
| P3-1 | Dockerfile + docker-compose（API + 可选 GPU 说明） | P0 |
| P3-2 | 桌面端设置页：本地 / 云端 Endpoint、超时、API Key 占位 | P0 |
| P3-3 | 云端鉴权与简单限流（MVP） | P1 |
| P3-4 | 异步任务接口（大图/多页：提交 → 轮询） | P1 |
| P3-5 | 部署文档与环境变量清单 | P0 |

### 3.3 验收标准

1. `docker compose up` 后可用与本地相同的 `/v1/recognize`  
2. 桌面端切换云端后，同一张样例图可完成识别  
3. 本地服务不可用时，有清晰降级/提示  

---

## Phase 4 — 精度、体验与正式发布

**优先级**：P2  
**时长估算**：4–6 周  
**依赖**：Phase 2 + 3  

### 4.1 目标

提升真实场景（手机拍照、光照不均）可用性，完成 Windows 安装包分发与基础质量保障。

### 4.2 主要任务

| ID | 任务 | 优先级 |
|----|------|--------|
| P4-1 | 拍照场景增强（透视变换、阴影、分辨率自适应） | P0 |
| P4-2 | 反复记号、倚音、连音线、多行歌词等结构扩展 | P1 |
| P4-3 | PyInstaller sidecar 与 Tauri 正式打包流水线（CI） | P0 |
| P4-4 | 崩溃上报/日志开关、性能优化（首包体积、冷启动） | P1 |
| P4-5 | 用户文档、快捷键、样例库 | P1 |
| P4-6 | v0.1.0 公开发布（GitHub Release） | P0 |

### 4.3 验收标准

1. 提供可下载的 Windows 安装包  
2. 真实手机照片样例集上达到约定可用阈值  
3. Release 附更新说明与已知问题  

---

## 4. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 简谱版式不统一 | 规则解析脆弱 | 先锁定 1–2 种常见模板；Schema 预留扩展 |
| PaddleOCR 模型体积大 | 安装包与冷启动 | PoC 开发态 pip 安装；发布期量化/裁剪或按需下载 |
| music21 与数字简谱语义差异 | 导出不准 | 内部 JSON 为真相源，导出做适配层 |
| Tauri sidecar 打包复杂度 | PoC 延期 | PoC 允许「手动启 Python + 开 UI」双进程；打包后置 |
| 样本与版权 | 测试数据受限 | 使用自制/授权样例，仓库只放可公开素材 |

---

## 5. 里程碑检查点

| 里程碑 | 标志性交付 |
|--------|------------|
| **M1 — Desktop PoC** | Windows 可运行；导入图 → 本地识别 → UI 展示 |
| M2 — OMR MVP | 结构化 JSON + 初级 MusicXML |
| M3 — 可用闭环 | 编辑 + 试听 + 导出 |
| M4 — 双模式 | 本地/云端切换可用 |
| M5 — v0.1 发布 | 安装包 + 文档 + 公开 Release |

---

## 6. 建议的初始目录结构

```text
EnPu/
├── README.md
├── ROADMAP.md
├── LICENSE
├── .gitignore
├── docs/                      # 架构说明、API、标注规范
│   ├── architecture.md
│   ├── api.md
│   └── jianpu-schema.md
├── samples/                   # 可公开的样例简谱图
│   └── README.md
├── core/                      # Python 识别核心（FastAPI）
│   ├── pyproject.toml         # 或 requirements.txt
│   ├── README.md
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── api/
│   │   │   └── v1/
│   │   │       └── recognize.py
│   │   ├── pipeline/
│   │   │   ├── preprocess.py  # OpenCV
│   │   │   ├── ocr.py         # PaddleOCR
│   │   │   ├── parse.py       # 简谱结构化
│   │   │   └── export.py      # music21
│   │   ├── schemas/           # Pydantic 模型
│   │   └── config.py
│   ├── tests/
│   └── Dockerfile
├── desktop/                   # Tauri 2 + React
│   ├── package.json
│   ├── src/                   # React UI
│   │   ├── components/
│   │   ├── pages/
│   │   ├── lib/api.ts         # 调用核心服务
│   │   └── App.tsx
│   ├── src-tauri/
│   │   ├── tauri.conf.json
│   │   └── ...
│   └── README.md
├── scripts/                   # 开发一键启动、打包辅助
│   ├── dev-core.ps1
│   └── dev-desktop.ps1
└── deploy/                    # 云端部署参考
    └── docker-compose.yml
```

---

## 7. PoC 阶段最推荐的最小实现路径

按严格串行依赖执行，避免过早优化识别精度与打包。

```text
Step 1  仓库与目录脚手架
        └─ monorepo 结构、.gitignore、README 开发说明
              │
Step 2  Python 核心「能跑」
        └─ FastAPI: GET /health
        └─ POST /v1/recognize  先返回 mock JSON
              │
Step 3  接上真实最小流水线
        └─ 收 multipart 图片 → OpenCV 灰度/二值化
        └─ PaddleOCR 跑整图 → 返回 texts + boxes
        └─ （可选）极简规则：把数字字符拼成 pitch 列表
              │
Step 4  桌面壳
        └─ Tauri 2 + React + Tailwind 空白窗体
              │
Step 5  UI 闭环
        └─ 选择图片 → 预览 → 调用 localhost:PORT/v1/recognize
        └─ 展示 OCR 文本列表 + JSON 原始结果
              │
Step 6  开发体验
        └─ scripts 一键启 core / desktop
        └─ samples/ 放入 1–2 张样例图
              │
Step 7  （时间允许）Windows 安装包或 sidecar
        └─ 不作为 M1 阻塞项；双进程开发态即可验收
```

**PoC 成功一句话**：  
> 「在 Windows 上打开 EnPu，丢一张简谱图，本地 Python 吐出 OCR/结构结果并显示在界面上。」

---

## 8. Issue 拆分索引（与 GitHub Issues 对应）

Issues 列表：https://github.com/loootte/EnPu/issues

| # | 标题 | 阶段 | 依赖 | 状态 |
|---|------|------|------|------|
| [#1](https://github.com/loootte/EnPu/issues/1) | [docs] 初始化 monorepo 目录与开发 README | P0 | — | ✅ |
| [#2](https://github.com/loootte/EnPu/issues/2) | [core] FastAPI 项目骨架与 /health、/v1/recognize | P0 | #1 | ✅ |
| [#3](https://github.com/loootte/EnPu/issues/3) | [core] OpenCV 预处理 + PaddleOCR 最小流水线 | P0 | #2 | ✅ |
| [#4](https://github.com/loootte/EnPu/issues/4) | [ui] Tauri 2 + React + TS + Tailwind 桌面壳 | P0 | #1 | ✅ |
| [#5](https://github.com/loootte/EnPu/issues/5) | [ui] 图片导入、预览与识别结果展示 | P0 | #4 | ✅ |
| [#6](https://github.com/loootte/EnPu/issues/6) | [poc] 桌面端与本地核心联调闭环 | P0 | #3 + #5 | ✅ |
| [#7](https://github.com/loootte/EnPu/issues/7) | [poc] 样例素材与 PoC 验收清单 | P0 | #6 | ✅ |
| [#8](https://github.com/loootte/EnPu/issues/8) | [poc]（可选）PyInstaller sidecar / 一键启动 | P0 | #3 | ✅ |
| [#9](https://github.com/loootte/EnPu/issues/9) | [core] 简谱 JSON Schema v0.1 与标注规范 | P1 | Phase 0 | ✅ |
| [#10](https://github.com/loootte/EnPu/issues/10) | [core] 音高/时值解析 MVP | P1 | #9 | ✅ |
| [#11](https://github.com/loootte/EnPu/issues/11) | [core] music21 导出 MusicXML/MIDI | P1 | #10 | ✅ |
| [#12](https://github.com/loootte/EnPu/issues/12) | [ui] 识别结果编辑、试听与导出 | P2 | #9 + #11 | ✅ |
| [#13](https://github.com/loootte/EnPu/issues/13) | [cloud] Docker 与本地/云端切换 | P3 | core 稳定 | ⬜ 下一步 |
| [#14](https://github.com/loootte/EnPu/issues/14) | [enhancement] Windows 安装包与 sidecar 打包 | P4 | Phase 0–2 | ⬜ |

---

## 9. 贡献与决策记录

| 日期 | 决策 |
|------|------|
| 2026-07-23 | 技术栈定为 Tauri2/React/TS/Tailwind + Python/FastAPI/OpenCV/PaddleOCR/music21 |
| 2026-07-23 | 架构：核心独立服务；本地 sidecar + 可选云端；UI 可切换 |
| 2026-07-23 | Milestone 1 = Windows 桌面 PoC，精度非目标 |
| 2026-07-23 | Phase 0 / M1 完成（#1–#8） |
| 2026-07-23 | Score Schema v0.1 定稿（#9）；OCR→Score 解析 MVP（#10）；下一步 #11 导出 |
| 2026-07-23 | music21 导出 MusicXML/MIDI MVP（#11，`POST /v1/export`）；下一步 #12 UI 或评测集 |
| 2026-07-24 | 桌面编辑/试听/导出 MVP（#12）；GitHub Actions CI（core pytest + desktop build） |

### Phase 0 完成摘要

- 桌面 Tauri + 本地 FastAPI 双进程可识别样例图并展示 OCR/JSON  
- 一键启停脚本、合成样例（CC0）、验收清单  
- Sidecar / Paddle 打包试验结论见 `docs/poc-sidecar.md`  

### Phase 1 进展摘要

- ✅ 内部 `Score` v0.1（Pydantic + JSON Schema + 标注规范）  
- ✅ `/v1/recognize` 返回 `score` + `parse_mode`（失败回退 hints / ocr_only）  
- ✅ 小节线 CV 恢复（OCR 丢 `|` 时注入）  
- ✅ MusicXML / MIDI 导出（music21 适配层 + `/v1/export`）  
- ⬜ 评测集与准确率基线；歌词精细对齐  

### Phase 2 进展摘要

- ✅ Score 编辑 UI（标题/调号/拍号/速度/音高/歌词/时值）  
- ✅ WebAudio 主旋律试听（时值近似）  
- ✅ 导出 JSON / MusicXML / MIDI；保存/打开 `.enpu.json` 工程  
- ✅ CI：`.github/workflows/ci.yml`（mock 核心测试 + 前端 build）  
- ⬜ 多页批处理；更强合成器 / 编辑器体验  

---

*本文档随迭代更新；Phase 1 完成后应固化准确率基线与导出覆盖范围。*
