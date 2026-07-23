# Scripts

## 一键启动 / 终止

### Windows PowerShell（推荐）

```powershell
.\scripts\start.ps1                 # core + Vite + 桌面（默认 paddleocr）
.\scripts\start.ps1 -Engine mock    # 快速 mock
.\scripts\start.ps1 -Ui vite        # 只要网页
.\scripts\stop.ps1
.\scripts\smoke-poc.ps1             # API 联调冒烟（需 core 已启动）
```

### Git Bash

```bash
./scripts/start.sh
./scripts/stop.sh
```

默认会启动：

| 服务 | 说明 |
|------|------|
| **Core** | http://127.0.0.1:8765（无控制台） |
| **Vite** | http://localhost:1420（无控制台） |
| **Desktop** | EnPu 窗口 |
| **Watcher** | 关桌面后自动 `stop` |

### 参数 / 环境变量

| PowerShell | 环境变量 | 默认 | 说明 |
|------------|----------|------|------|
| `-Ui` | `ENPU_UI` | `both` | `both` / `vite` / `none` |
| `-DesktopMode` | `ENPU_DESKTOP_MODE` | `auto` | `auto` / `exe` / `dev` |
| `-Engine` | `ENPU_RECOGNIZE_ENGINE` | `paddleocr` | `paddleocr` / `mock` |
| `-AutoStop` | `ENPU_AUTO_STOP` | `$true` / `1` | 关桌面是否停服务 |
| `-CorePort` | `ENPU_CORE_PORT` | `8765` | 核心端口 |
| `-VitePort` | `ENPU_VITE_PORT` | `1420` | Vite 端口 |

桌面 UI 识别地址：`VITE_ENPU_CORE_URL`（见 `desktop/.env.example`）。

---

## 联调闭环（Issue #6）

1. `.\scripts\start.ps1 -Engine mock`（或 paddleocr）  
2. `.\scripts\smoke-poc.ps1` → health + recognize 样例  
3. 打开桌面/网页 → 导入 `samples/001_poc_digits.png` → 开始识别  
4. `.\scripts\stop.ps1`  

完整勾选表：[docs/poc-acceptance.md](../docs/poc-acceptance.md)

---

## 分进程（前台调试）

| 脚本 | 作用 |
|------|------|
| `dev-core.ps1` | 仅 core（前台，带 reload） |
| `dev-desktop.ps1` | 仅 Tauri（前台） |

---

## Core Sidecar 打包（Issue #8）

```powershell
.\scripts\build-core-sidecar.ps1
.\core\dist\enpu-core.exe --engine mock --port 8765
```

见 [docs/poc-sidecar.md](../docs/poc-sidecar.md)。

---

## 日志

`scripts/.run/logs/`（gitignore）
