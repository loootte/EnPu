# EnPu Desktop — 桌面端

**Tauri 2 + React + TypeScript + Tailwind** 桌面应用。

通过 HTTP 调用本地或云端 `core` 识别服务（联调见 Issue #6）。

## 环境要求（Windows）

| 组件 | 说明 |
|------|------|
| Node.js | 20+（推荐 LTS） |
| Rust | stable（[rustup](https://rustup.rs/)） |
| MSVC 工具链 | Visual Studio Build Tools：**Desktop development with C++** / `VCTools` 工作负载 |
| WebView2 | Windows 10/11 通常已自带 |

官方前置条件：https://v2.tauri.app/start/prerequisites/

### 安装 Rust

```powershell
# https://rustup.rs/
winget install Rustlang.Rustup
# 或下载 rustup-init.exe 后：
# .\rustup-init.exe -y
```

### 安装 C++ 生成工具（若 `tauri dev` 报 link.exe / MSVC 缺失）

安装 [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)，勾选：

- **使用 C++ 的桌面开发**（或 workload `Microsoft.VisualStudio.Workload.VCTools`）

## 开发启动

```powershell
cd desktop
npm install
npm run tauri dev
# 等价：npm run tauri:dev
```

仓库根目录：

```powershell
.\scripts\dev-desktop.ps1
```

成功后应弹出窗口标题 **「EnPu · 恩谱」**，界面为深色 Tailwind 壳，并可点击「调用 greet」验证 Rust 命令。

仅前端（无原生窗口）：

```powershell
npm run dev
# http://localhost:1420
```

## 目录

```text
desktop/
├── src/
│   ├── App.tsx           # 壳页面（#4）
│   ├── index.css         # Tailwind 入口
│   ├── components/       # #5 UI 组件
│   ├── pages/
│   └── lib/api.ts        # core HTTP 客户端（#6 扩展）
├── src-tauri/
│   ├── tauri.conf.json
│   ├── Cargo.toml
│   └── src/
├── package.json
└── README.md
```

## 实现状态

| 能力 | Issue | 状态 |
|------|-------|------|
| Tauri 2 + React + TS + Tailwind 壳 | #4 | **本版本** |
| 导入 / 预览 / 结果展示 | #5 | 待实现 |
| 本地 core 联调 | #6 | 待实现 |

## 常见问题

**`error: linker 'link.exe' not found`**  
未安装 MSVC。见上文 C++ 生成工具。

**首次 `tauri dev` 很慢**  
Cargo 编译依赖，首次可能数分钟，属正常。

**与 core 联调**  
先 `.\scripts\dev-core.ps1` 再开桌面；识别 UI 在 #5/#6。
