# EnPu Desktop — 桌面端

**Tauri 2 + React + TypeScript + Tailwind** 桌面应用。

通过 HTTP 调用本地或云端 `core` 识别服务。

## 目录（目标）

```text
desktop/
├── src/                 # React UI
│   ├── components/
│   ├── pages/
│   ├── lib/api.ts       # 调用 core
│   └── App.tsx
├── src-tauri/           # Tauri 原生工程
├── package.json
└── README.md
```

> 当前为 monorepo 占位；完整 Tauri 工程由 Issue [#4](https://github.com/loootte/EnPu/issues/4) 初始化。

## 环境要求

- Node.js 20+  
- Rust（rustup，stable）  
- Windows：WebView2、C++ 构建工具（Tauri 官方要求）  

参考：[Tauri 2 前置条件](https://v2.tauri.app/start/prerequisites/)

## 开发启动（目标命令）

```powershell
cd desktop
npm install
npm run tauri dev
```

或在仓库根目录：

```powershell
.\scripts\dev-desktop.ps1
```

## 与 core 的联调

1. 先启动 core：`http://127.0.0.1:8765`  
2. 再启动 desktop  
3. UI 默认请求本地 `POST /v1/recognize`  

详见根 [README.md](../README.md) 与 Issue [#6](https://github.com/loootte/EnPu/issues/6)。

## 实现状态

| 能力 | Issue | 状态 |
|------|-------|------|
| Tauri 2 + React + TS + Tailwind 壳 | [#4](https://github.com/loootte/EnPu/issues/4) | 待实现 |
| 导入 / 预览 / 结果展示 | [#5](https://github.com/loootte/EnPu/issues/5) | 待实现 |
| 本地联调闭环 | [#6](https://github.com/loootte/EnPu/issues/6) | 待实现 |
