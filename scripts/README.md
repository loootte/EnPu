# Scripts

## 一键启动 / 终止（bash）

适用于 **Git Bash（Windows）**、macOS、Linux。

### 启动（默认会开桌面窗口）

```bash
chmod +x scripts/start.sh scripts/stop.sh   # 首次
./scripts/start.sh
```

默认会启动：

| 服务 | 说明 |
|------|------|
| **Core** | FastAPI → http://127.0.0.1:8765（**无控制台窗口**） |
| **Vite** | Web UI → http://localhost:1420（**无控制台窗口**） |
| **Desktop** | Tauri 窗口 `enpu-desktop`（恩谱） |
| **Watcher** | 关闭桌面窗口后，**自动**执行 `stop.sh` 停掉 core + UI |

桌面启动策略（`ENPU_DESKTOP_MODE`，默认 `auto`）：

1. **auto**：若存在已编译的 `enpu-desktop.exe` / 二进制 → 直接打开窗口（快）  
2. 否则走 **`tauri dev`**（热更新，首次编译可能较久）  
3. 强制：`ENPU_DESKTOP_MODE=exe` 或 `ENPU_DESKTOP_MODE=dev`

### 终止

```bash
./scripts/stop.sh
./scripts/stop.sh --ports-only
```

会停止 core、Vite，并结束 `enpu-desktop` 进程。

### 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `ENPU_UI` | `both` | `both`（推荐）/ `vite` / `none` |
| `ENPU_DESKTOP_MODE` | `auto` | `auto` / `exe` / `dev` |
| `ENPU_AUTO_STOP` | `1` | `1`=关桌面后停 core+UI；`0`=不自动停 |
| `ENPU_RECOGNIZE_ENGINE` | `paddleocr` | `paddleocr` 或 `mock` |
| `ENPU_CORE_HOST` | `127.0.0.1` | 核心绑定地址 |
| `ENPU_CORE_PORT` | `8765` | 核心端口 |
| `ENPU_VITE_PORT` | `1420` | Vite 端口 |

示例：

```bash
# 默认：core + 网页 + 桌面窗
./scripts/start.sh

# 只要浏览器 UI，不要桌面窗
ENPU_UI=vite ./scripts/start.sh

# 强制用已编译 exe 开窗（快）
ENPU_DESKTOP_MODE=exe ./scripts/start.sh

# 强制 tauri dev（热更新）
ENPU_DESKTOP_MODE=dev ./scripts/start.sh

# mock 引擎（不下载 Paddle）
ENPU_RECOGNIZE_ENGINE=mock ./scripts/start.sh
```

### 首次没有桌面 exe？

在仓库里编译一次 debug 包（之后 `auto`/`exe` 就能秒开）：

```bash
cd desktop
npm install
# Windows 需已装 VS Build Tools (C++)
npm run tauri build -- --debug
```

产物：`desktop/src-tauri/target/debug/enpu-desktop.exe`

### 日志与 PID

- PID：`scripts/.run/pids.env`
- 日志：`scripts/.run/logs/core.log`、`vite.log`、`tauri.log`

### Windows 提示

1. 用 **Git Bash** 运行  
2. 桌面窗依赖 WebView2（Win10/11 一般已有）  
3. `tauri dev` 需要 Rust + MSVC；仅用预编译 exe 时不需要每次编译  

### 分进程脚本（PowerShell）

| 脚本 | 作用 |
|------|------|
| `dev-core.ps1` | 仅 core（前台） |
| `dev-desktop.ps1` | 仅 Tauri（前台） |

### Core Sidecar 打包（Issue #8 PoC）

将 FastAPI 核心打成独立 `enpu-core.exe`（默认 **mock** 引擎，约 ~100MB；不含 Paddle）：

```powershell
.\scripts\build-core-sidecar.ps1
.\core\dist\enpu-core.exe --engine mock --port 8765
```

```bash
./scripts/build-core-sidecar.sh
```

试验结论与体积/冷启动数据见 [docs/poc-sidecar.md](../docs/poc-sidecar.md)。
