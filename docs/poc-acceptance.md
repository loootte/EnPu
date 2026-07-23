# Phase 0 / Milestone 1 — PoC 验收清单（Issue #6）

> **成功一句话**：在 Windows 上打开 EnPu，丢一张简谱图，本地 Python 吐出 OCR/结构结果并显示在界面上。

**日期**：________　　**验收人**：________

---

## 0. 前置

| # | 检查项 | 通过 |
|---|--------|------|
| 0.1 | 已安装 Git / Python 3.10+ / Node 20+ | ☐ |
| 0.2 | （桌面窗）Rust + VS C++ Build Tools；或已有 `enpu-desktop.exe` | ☐ |
| 0.3 | 仓库最新 `main` 或含 #5+#8 的分支 | ☐ |
| 0.4 | 样例图存在：`samples/001_poc_digits.png` | ☐ |

---

## 1. 30 分钟内可启动（DoD-1）

任选一种启动方式：

### A. PowerShell 一键（推荐 Windows）

```powershell
cd <repo>
.\scripts\start.ps1 -Engine mock   # 快速；真实 OCR 用默认 paddleocr
```

### B. Git Bash 一键

```bash
./scripts/start.sh
# 或：ENPU_RECOGNIZE_ENGINE=mock ./scripts/start.sh
```

### C. 双进程手动

```powershell
# 终端 A
.\scripts\dev-core.ps1
# 终端 B
.\scripts\dev-desktop.ps1
# 或：cd desktop && npm run dev   → http://localhost:1420
```

| # | 检查项 | 通过 |
|---|--------|------|
| 1.1 | `GET http://127.0.0.1:8765/health` 返回 `status=ok` | ☐ |
| 1.2 | OpenAPI 可开：http://127.0.0.1:8765/docs | ☐ |
| 1.3 | Web UI 或桌面窗可打开（localhost:1420 或 EnPu 窗口） | ☐ |

自动化（core 已启动时）：

```powershell
.\scripts\smoke-poc.ps1
```

---

## 2. 导入样例并识别（DoD-2 / DoD-3）

| # | 检查项 | 通过 |
|---|--------|------|
| 2.1 | UI 可选择/拖入 `samples/001_poc_digits.png` 并预览 | ☐ |
| 2.2 | 点击「开始识别」后 **60 秒内** 返回结果（首次 Paddle 可更长） | ☐ |
| 2.3 | 结果区可见：OCR 文本列表 和/或 JSON（及可选音高提示） | ☐ |
| 2.4 | 顶部显示核心在线 / engine 信息 | ☐ |

API 侧对照：

```powershell
curl.exe -X POST http://127.0.0.1:8765/v1/recognize -F "file=@samples/001_poc_digits.png"
```

---

## 3. 失败路径（DoD-4）

| # | 检查项 | 通过 |
|---|--------|------|
| 3.1 | core 未启动时，UI 有可读错误（连接失败 / 提示启动脚本） | ☐ |
| 3.2 | 选择非 png/jpg 时有格式错误提示 | ☐ |
| 3.3 | （可选）stop 后 health 不可达 | ☐ |

```powershell
.\scripts\stop.ps1
# 或 ./scripts/stop.sh
```

---

## 4. 联调闭环摘要

| 路径 | 组件 |
|------|------|
| 图片 | `ImagePicker` → File / ObjectURL 预览 |
| HTTP | `desktop/src/lib/api.ts` → `POST {base}/v1/recognize` |
| 默认 Base | `http://127.0.0.1:8765`（`VITE_ENPU_CORE_URL` 可覆盖） |
| 核心 | FastAPI `core/app` · OpenCV + PaddleOCR / mock |
| 启停 | `scripts/start.ps1` · `start.sh` · `stop.ps1` · `stop.sh` |

配置示例：`desktop/.env.example` → 复制为 `desktop/.env`。

---

## 5. 已知限制（非失败项）

- 识别精度非 Phase 0 目标；合成样例上数字可能粘连  
- 首次 Paddle 下载模型需网络与时间  
- 正式 PyInstaller + Tauri sidecar 集成见 Phase 4 / #14；试验见 `docs/poc-sidecar.md`  
- 关桌面自动停服务：`ENPU_AUTO_STOP=1`（默认）  

---

## 6. 结论

| 项 | 是 / 否 |
|----|---------|
| Milestone 1（桌面 PoC）验收通过 | ☐ |
| 备注 | |

验收人签名：________　　日期：________
