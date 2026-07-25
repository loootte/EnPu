# EnPu（恩谱）

**中文敬拜简谱 OMR 数字化工具**

把扫描/拍照的中文敬拜简谱（数字谱）识别成可编辑、可播放、可导出的数字化乐谱，方便教会敬拜团队使用。

目标导出格式：**MusicXML** / **MIDI** / **EnPu JSON**。

| 资源 | 链接 |
|------|------|
| 路线图 | [ROADMAP.md](./ROADMAP.md) |
| Issues | [GitHub Issues](https://github.com/loootte/EnPu/issues) |
| 许可证 | [Apache-2.0](./LICENSE) |

---

## 技术栈

| 层级 | 选型 |
|------|------|
| 桌面 UI | Tauri 2 + React + TypeScript + Tailwind |
| 识别核心 | Python + FastAPI |
| 图像处理 | OpenCV |
| 文字/数字 OCR | PaddleOCR |
| 乐谱结构化 / 导出 | music21 |
| 本地集成 | 开发态双进程；发布期 PyInstaller sidecar |
| 云端 | 同一套 FastAPI + Docker |

```text
┌─────────────────────────────┐
│  desktop/  Tauri + React    │
│  导入图片 · 预览 · 展示结果   │
└──────────────┬──────────────┘
               │ HTTP (localhost 或云端)
               ▼
┌─────────────────────────────┐
│  core/  FastAPI OMR 服务     │
│  OpenCV → PaddleOCR → …     │
└─────────────────────────────┘
```

### 结构优先识别（#58，可选）

默认 `ENPU_PIPELINE_MODE=legacy`（整页 OCR → 规则拼装）。设为 **`structure`** 时走分层内核：

```text
L1  页面级     标题 / 调号 / 拍号 / 主谱面 ROI
L2  主谱面     谱行（systems；pitch+和弦+歌词绑定为同一行）
L3  谱行内     小节线 → 小节（measures）
L4  小节内     音符 / 和弦 / 歌词候选 ROI（几何为主）
L5  音符节点   音高数字 OCR（+几何兜底）+ 时值线 / 高低音点等几何
               → 组装 Score JSON
```

| 原则 | 说明 |
|------|------|
| L1–L4 | **OpenCV / 几何 / 版面**为主，不依赖整页 OCR 文本顺序 |
| L5 | **音高数字**以 OCR 为主，并与同节点几何特征绑定 |
| 开关 | `ENPU_PIPELINE_MODE=structure` 或 `legacy` |

桌面在结构模式下可叠图查看 L1–L5。完整说明见 [docs/architecture-structure-first.md](./docs/architecture-structure-first.md) · [docs/architecture.md](./docs/architecture.md)。

---

## 仓库结构

```text
EnPu/
├── core/          # Python 识别核心（FastAPI）
├── desktop/       # Tauri 2 桌面端
├── docs/          # 架构、API、Schema 文档
├── samples/       # 可公开样例简谱图
├── scripts/       # 开发启动脚本（Windows PowerShell）
├── deploy/        # Docker / 云端部署参考
├── ROADMAP.md     # 产品与技术路线图
└── README.md
```

当前阶段：**Phase 1 基线已测**（print_clear Pitch F1 ≥60%）；下一阶段 **结构精度**（非谱行过滤 / 小节划分）与 **v0.1.0**。详见 [ROADMAP.md](./ROADMAP.md) · [eval-baseline.md](./docs/eval-baseline.md)。

### CI / 发布

Push / PR 到 `main` 时 GitHub Actions 会：

1. **core**：安装 `core/requirements-ci.txt`（无 Paddle）并以 mock 引擎跑 `pytest`  
2. **desktop**：`npm ci` + `npm run build`（tsc + Vite）  
3. **eval-print-clear**：PaddleOCR 跑合成 `print_clear` 子集，加权 Pitch F1 **≥ 60%** 才通过（#38）

工作流：`.github/workflows/ci.yml`  

**Windows 安装包（#14）**：

```powershell
.\scripts\build-release.ps1
```

- 文档：[docs/release-windows.md](./docs/release-windows.md)  
- **CD**：GitHub Actions → **CD Windows**（`.github/workflows/cd-windows.yml`）  
  - 手动 Run workflow，或 `git push origin v0.1.0`  
  - 产物：NSIS setup + sidecar + SHA256，Artifacts 可下载；tag 推送会挂 Release  

---

## 环境要求（Windows 开发）

| 组件 | 建议版本 | 用途 |
|------|----------|------|
| Git | 2.x | 版本管理 |
| Python | 3.10+（推荐 3.11/3.12） | `core/` 识别服务 |
| Node.js | 20 LTS 或更新 | `desktop/` 前端 |
| Rust | stable（rustup） | Tauri 2 构建 |
| Visual Studio C++ 生成工具 | 较新版本 | Tauri / 原生依赖 |
| WebView2 | Windows 10/11 通常已自带 | Tauri 运行时 |

> PoC 阶段采用 **双进程开发**：先手动启动 `core`，再启动 `desktop`。Sidecar 一体化打包见后续 Issue。

---

## 快速开始（开发态）

### 1. 克隆仓库

```powershell
git clone https://github.com/loootte/EnPu.git
cd EnPu
```

### 2. 一键启动 / 终止（推荐）

**PowerShell（Windows）**

```powershell
.\scripts\start.ps1                 # core + Vite + 桌面
.\scripts\start.ps1 -Engine mock    # 快速联调
.\scripts\smoke-poc.ps1             # API 冒烟（health + 样例识别）
.\scripts\stop.ps1
```

**Git Bash**

```bash
./scripts/start.sh
./scripts/stop.sh
```

| 服务 | 地址 / 说明 |
|------|-------------|
| Core | http://127.0.0.1:8765/health |
| Web UI | http://localhost:1420 |
| Desktop | 原生窗口 **EnPu · 恩谱** |
| API 文档 | http://127.0.0.1:8765/docs |

更多选项：[scripts/README.md](./scripts/README.md)。

### 3. 分进程启动（调试）

```powershell
.\scripts\dev-core.ps1      # 终端 A
.\scripts\dev-desktop.ps1   # 终端 B
```

### 4. PoC 验收路径

1. `.\scripts\start.ps1` 启动  
2. `.\scripts\smoke-poc.ps1` 或 UI 导入 `samples/001_poc_digits.png`  
3. 界面/API 得到 OCR 文本或 JSON  
4. `.\scripts\stop.ps1`  

勾选清单：[docs/poc-acceptance.md](./docs/poc-acceptance.md)（Issue #6）。

---

## 模块说明

| 目录 | 说明 | 入口文档 |
|------|------|----------|
| [`core/`](./core/) | FastAPI 识别服务、流水线、导出 | [core/README.md](./core/README.md) |
| [`desktop/`](./desktop/) | Tauri 桌面 UI | [desktop/README.md](./desktop/README.md) |
| [`docs/`](./docs/) | 架构与规范 | [docs/architecture.md](./docs/architecture.md) |
| [`samples/`](./samples/) | 样例图片（仅可公开素材） | [samples/README.md](./samples/README.md) |
| [`deploy/`](./deploy/) | Docker Compose 参考 | [deploy/docker-compose.yml](./deploy/docker-compose.yml) |

---

## 开发约定

1. **Issue 驱动**：功能开发对应 GitHub Issue；分支建议 `feature/<issue号>-简短描述`  
2. **PR 回 `main`**：小步提交，描述关联 Issue（如 `Closes #1`）  
3. **核心独立**：识别逻辑只放在 `core/`，桌面端只通过 HTTP 调用  
4. **不提交密钥与大模型文件**：见 `.gitignore`  
5. **样例版权**：仅提交自制或已授权素材  

---

## 当前状态

- [x] 路线图与 Issue 拆分  
- [x] Monorepo 目录与开发文档脚手架（#1）  
- [x] FastAPI 骨架 + mock `/v1/recognize`（#2）  
- [x] OpenCV + PaddleOCR 识别流水线（#3）  
- [x] Tauri 2 桌面壳（#4）  
- [x] 识别 UI：导入 / 预览 / 结果（#5）  
- [x] 一键启停 + sidecar 试验（#8）  
- [x] 本地联调闭环（#6，`start.ps1` / `smoke-poc.ps1` / `docs/poc-acceptance.md`）  
- [x] 样例素材与验收清单（#7，`samples/` · `docs/poc-acceptance.md`）  
- [x] 简谱 JSON Schema v0.1（#9，`docs/jianpu-schema.md`）  
- [x] OCR → Score 解析 MVP（#10）  

---

## 贡献

1. Fork / 检出分支  
2. 完成改动并自测  
3. 打开 PR 指向 `main`，关联对应 Issue  

问题与想法请开 [Issue](https://github.com/loootte/EnPu/issues)。

---

## License

[Apache License 2.0](./LICENSE)
