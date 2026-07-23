# Scripts

## 一键启动 / 终止（bash）

适用于 **Git Bash（Windows）**、macOS、Linux。

### 启动

```bash
# 仓库根目录
chmod +x scripts/start.sh scripts/stop.sh   # 首次
./scripts/start.sh
```

默认：

| 服务 | 地址 |
|------|------|
| Core (FastAPI) | http://127.0.0.1:8765 |
| UI (Vite) | http://localhost:1420 |
| API 文档 | http://127.0.0.1:8765/docs |

### 终止

```bash
./scripts/stop.sh
# 或仅按端口清理：
./scripts/stop.sh --ports-only
```

### 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `ENPU_UI` | `vite` | `vite` / `tauri` / `both` / `none` |
| `ENPU_RECOGNIZE_ENGINE` | `paddleocr` | `paddleocr` 或 `mock` |
| `ENPU_CORE_HOST` | `127.0.0.1` | 核心绑定地址 |
| `ENPU_CORE_PORT` | `8765` | 核心端口 |

示例：

```bash
# 离线 mock，不下载 Paddle 模型
ENPU_RECOGNIZE_ENGINE=mock ./scripts/start.sh

# 只起核心
ENPU_UI=none ./scripts/start.sh

# 尝试 Tauri 窗口（需 Rust + Windows MSVC）
ENPU_UI=tauri ./scripts/start.sh
```

### 日志与 PID

- PID：`scripts/.run/pids.env`（已 gitignore）
- 日志：`scripts/.run/logs/core.log`、`vite.log`、`tauri.log`

### Windows 提示

1. 用 **Git Bash** 运行：`"C:\Program Files\Git\bin\bash.exe" ./scripts/start.sh`
2. 首次 core 会 `pip install`，Paddle 首次识别会下载模型  
3. Tauri 一键启动在无 MSVC 环境下可能失败；日常开发推荐默认 `vite` UI  

### 分进程脚本（PowerShell）

| 脚本 | 作用 |
|------|------|
| `dev-core.ps1` | 仅启动 core（前台） |
| `dev-desktop.ps1` | 仅启动 Tauri（前台） |
