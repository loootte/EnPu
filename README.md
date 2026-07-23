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

当前阶段：**Phase 0 — 桌面端 PoC**（先证明技术路线可行，不追求识别精度）。详见 [ROADMAP.md](./ROADMAP.md)。

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

> 下列命令为 **目标工作流**。`core` / `desktop` 的可运行实现分别在 [#2](https://github.com/loootte/EnPu/issues/2)、[#4](https://github.com/loootte/EnPu/issues/4) 落地；脚手架就绪后命令即可生效。

### 1. 克隆仓库

```powershell
git clone https://github.com/loootte/EnPu.git
cd EnPu
```

### 2. 启动识别核心（终端 A）

```powershell
# 进入核心目录并创建虚拟环境
cd core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 启动 API（默认 http://127.0.0.1:8765）
# 实现就绪后：
# uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
.\..\scripts\dev-core.ps1
```

健康检查（服务起来后）：

```powershell
curl http://127.0.0.1:8765/health
# 期望: {"status":"ok"}
```

OpenAPI 文档：<http://127.0.0.1:8765/docs>

### 3. 启动桌面端（终端 B）

```powershell
cd desktop
npm install
# 实现就绪后：
# npm run tauri dev
.\..\scripts\dev-desktop.ps1
```

### 4. PoC 验收路径（目标）

1. 打开桌面窗口  
2. 从 `samples/` 导入一张简谱图  
3. 点击识别 → 调用本地 `POST /v1/recognize`  
4. 界面展示 OCR 文本或 JSON 结果  

联调与验收清单见 Issue [#6](https://github.com/loootte/EnPu/issues/6)、[#7](https://github.com/loootte/EnPu/issues/7)。

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
- [x] Monorepo 目录与开发文档脚手架（本 PR / #1）  
- [ ] FastAPI 骨架与识别流水线（#2、#3）  
- [ ] Tauri 桌面壳与识别 UI（#4、#5）  
- [ ] 本地联调闭环（#6）  

---

## 贡献

1. Fork / 检出分支  
2. 完成改动并自测  
3. 打开 PR 指向 `main`，关联对应 Issue  

问题与想法请开 [Issue](https://github.com/loootte/EnPu/issues)。

---

## License

[Apache License 2.0](./LICENSE)
