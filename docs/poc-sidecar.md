# PoC：Core Sidecar 与一键启动（Issue #8）

> Phase 0 非阻塞试验。正式 Tauri sidecar 集成见 Phase 4 / Issue #14。

**日期**：2026-07-23  
**分支**：`feature/scripts-start-stop`  
**机器**：Windows 11 · Python 3.12 · PyInstaller 6.21

---

## 1. 目标

1. 验证 Python 识别核心能否打包成独立可执行文件（sidecar 雏形）  
2. 提供 **一键启动 core + desktop** 脚本并文档化  
3. 记录体积、冷启动、模型路径等风险  

---

## 2. 一键启动 / 终止（推荐日常开发）

已实现（不依赖 PyInstaller）：

| 脚本 | 作用 |
|------|------|
| `scripts/start.sh` | 后台启动 core + Vite + 桌面窗（无控制台） |
| `scripts/stop.sh` | 一键停止 |
| `scripts/desktop-watcher.ps1` | 关桌面后自动停 core/UI |

```bash
./scripts/start.sh
./scripts/stop.sh
```

详见 [scripts/README.md](../scripts/README.md)。

**结论**：日常 PoC 开发以「venv + start.sh」为主即可，无需 sidecar。

---

## 3. PyInstaller 试验

### 3.1 产物

| 项 | 结果 |
|----|------|
| 命令 | `scripts/build-core-sidecar.ps1` / `build-core-sidecar.sh` |
| 入口 | `core/run_server.py` |
| Spec | `core/enpu-core.spec` |
| 输出 | `core/dist/enpu-core.exe`（gitignore，不进仓库） |
| 体积 | **约 107 MB**（onefile，含 OpenCV/Numpy/FastAPI，**排除** Paddle） |
| 默认引擎 | `mock`（`--engine mock`） |

### 3.2 冒烟结果（本机）

```text
enpu-core.exe --engine mock --host 127.0.0.1 --port 8765
GET  /health          → 200  {"status":"ok","engine":"mock",...}
POST /v1/recognize    → 200  mock texts + notes
冷启动到 /health 就绪  → 约 3.6 s
```

### 3.3 明确不做 / 延后

| 项 | 说明 |
|----|------|
| 打包 PaddleOCR | 模型 + 原生库极大（GB 级风险），首次下载与路径 `_MEIPASS` 复杂 |
| Tauri 自动拉起 sidecar | Phase 4；当前桌面仍 HTTP 连 venv 或独立 exe |
| UPX 压缩 | 关闭（杀软误报与启动变慢风险） |

若强制打入 Paddle，预期问题：

1. 体积膨胀到数百 MB～数 GB  
2. 模型缓存默认 `~/.paddleocr`，打包后需自定义 `home` / 环境变量  
3. DLL 搜索路径与 OpenCV/Paddle 冲突概率高  

---

## 4. 构建与运行

### 构建

```powershell
# Windows
.\scripts\build-core-sidecar.ps1
```

```bash
# Git Bash / Linux / macOS
./scripts/build-core-sidecar.sh
```

### 运行 sidecar

```powershell
.\core\dist\enpu-core.exe --engine mock --host 127.0.0.1 --port 8765
curl http://127.0.0.1:8765/health
```

桌面 UI 仍指向 `http://127.0.0.1:8765` 即可（与 venv 模式相同）。

---

## 5. 评估摘要

| 维度 | 评估 |
|------|------|
| 可行性 | **可行**：mock 流水线可打包并通过 API 冒烟 |
| 体积 | ~107 MB（可接受为开发/演示 sidecar；正式需裁剪） |
| 冷启动 | ~3–5 s（本机 mock） |
| 模型路径 | mock 无模型；Paddle 路径策略 **未解决**（延后） |
| 一键体验 | **start.sh 已覆盖** 双进程 + 桌面 + 自动停 |
| Phase 0 | **不阻塞**；推荐继续 venv 开发 |

---

## 6. 后续（Phase 4 / #14 — 已落地 MVP）

正式打包说明见 **[release-windows.md](./release-windows.md)**：

1. ✅ Tauri `externalBin` 挂载 `enpu-core` + 应用生命周期 start/stop  
2. ⬜ 按需下载 OCR 模型（安装后首次识别）而非打进 exe  
3. ⬜ onedir 模式便于增量更新 DLL  
4. ✅ CI：`release-windows.yml` 构建 NSIS + sidecar artifact / Release  

---

## 7. 验收勾选（#8）

- [x] 文档记录试验结果（成功步骤 + 阻塞点）  
- [x] 一键启动 core + desktop 脚本与说明  
- [x] PyInstaller 打包试验（mock 成功；Paddle 延后）  
- [x] 不阻塞 Phase 0 主验收  

**Issue #8 可关闭。**
