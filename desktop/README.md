# EnPu Desktop — 桌面端

**Tauri 2 + React + TypeScript + Tailwind** 桌面应用。

通过 HTTP 调用本地或云端 `core` 识别服务。

## 功能（当前）

| 能力 | 状态 |
|------|------|
| Tauri 窗口壳 | ✅ #4 |
| 图片导入 / 拖拽 / 预览 | ✅ #5 |
| 调用 `/v1/recognize` 并展示 OCR / notes / JSON | ✅ #5 |
| 核心在线状态指示 | ✅ #5 |
| 一键双进程联调脚本打磨 | #6 |

## 环境要求（Windows）

| 组件 | 说明 |
|------|------|
| Node.js | 20+ |
| Rust | stable（[rustup](https://rustup.rs/)） |
| MSVC | Visual Studio Build Tools + C++ 工作负载 |
| WebView2 | Windows 10/11 通常已自带 |

https://v2.tauri.app/start/prerequisites/

## 开发启动

**终端 A — 识别核心**

```powershell
# 仓库根目录
.\scripts\dev-core.ps1
# → http://127.0.0.1:8765
```

**终端 B — 桌面**

```powershell
cd desktop
npm install
npm run tauri dev
# 或：.\scripts\dev-desktop.ps1
```

仅前端（浏览器预览 UI，仍可调本地 core）：

```powershell
npm run dev
# http://localhost:1420
```

### 使用流程

1. 确认 header 显示「核心在线」  
2. 选择或拖入 `samples/001_poc_digits.png`（或任意 png/jpg）  
3. 点击 **开始识别**  
4. 右侧查看 OCR 文本 / 音高提示 / JSON  

若核心未启动，界面会提示连接失败。

### 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `VITE_ENPU_CORE_URL` | `http://127.0.0.1:8765` | 识别核心 Base URL |

## 目录

```text
desktop/src/
├── App.tsx
├── pages/RecognizePage.tsx
├── components/
│   ├── ImagePicker.tsx
│   ├── ImagePreview.tsx
│   ├── ResultPanel.tsx
│   └── StatusBanner.tsx
└── lib/
    ├── api.ts      # health + recognize
    └── types.ts
```

## 常见问题

**`linker 'link.exe' not found`**  
安装 VS Build Tools（C++）。

**识别一直失败 / 核心离线**  
先启动 core；检查防火墙是否拦截 localhost:8765。

**首次 PaddleOCR 很慢**  
core 首次下载模型，属正常。
