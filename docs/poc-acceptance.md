# Phase 0 / Milestone 1 — PoC 验收清单

> **成功一句话**：在 Windows 上打开 EnPu，丢一张简谱图，本地 Python 吐出 OCR/结构结果并显示在界面上。  
> 关联：Issue **#6**（联调闭环）、Issue **#7**（样例与清单）。

**日期**：________　　**验收人**：________　　**引擎**：mock / paddleocr（圈选）

---

## 0. 前置

| # | 检查项 | 通过 |
|---|--------|------|
| 0.1 | 已安装 Git / Python 3.10+ / Node 20+ | ☐ |
| 0.2 | （桌面窗）Rust + VS C++ Build Tools；或已有 `enpu-desktop.exe` | ☐ |
| 0.3 | 仓库为最新 `main` | ☐ |
| 0.4 | 样例目录完整（见下表，≥2 张） | ☐ |

### 样例资产（#7）

| 文件 | 存在 | 说明 |
|------|------|------|
| `samples/001_poc_digits.png` | ☐ | 清晰合成谱（默认冒烟） |
| `samples/002_scan_like.png` | ☐ | 轻微倾斜/噪声 |
| `samples/003_cn_lyrics.png` | ☐ | 中文示意歌词（可选若字体生成失败） |
| `samples/README.md` 含授权说明（CC0 / 自制） | ☐ | 无未授权版权素材 |

再生样例（可选）：

```powershell
.\core\.venv\Scripts\python.exe .\scripts\generate-samples.py
```

---

## 1. 30 分钟内可启动（DoD-1）

### A. PowerShell 一键（推荐）

```powershell
cd <repo>
.\scripts\start.ps1 -Engine mock
```

### B. Git Bash

```bash
./scripts/start.sh
```

### C. 双进程

```powershell
.\scripts\dev-core.ps1
.\scripts\dev-desktop.ps1
```

| # | 检查项 | 通过 |
|---|--------|------|
| 1.1 | `GET http://127.0.0.1:8765/health` → `status=ok` | ☐ |
| 1.2 | http://127.0.0.1:8765/docs 可打开 | ☐ |
| 1.3 | Web UI（:1420）或桌面窗可打开 | ☐ |

自动化：

```powershell
.\scripts\smoke-poc.ps1
.\scripts\smoke-poc.ps1 -Sample .\samples\002_scan_like.png
```

| # | 检查项 | 通过 |
|---|--------|------|
| 1.4 | `smoke-poc.ps1` 对 001 输出 `SMOKE PASSED` | ☐ |
| 1.5 | （建议）对 002 同样通过 | ☐ |

---

## 2. 导入样例并识别（DoD-2 / DoD-3）

| # | 检查项 | 通过 |
|---|--------|------|
| 2.1 | UI 导入 `001_poc_digits.png` 并预览 | ☐ |
| 2.2 | 「开始识别」后合理时间内返回（mock 数秒；Paddle 首次可更长） | ☐ |
| 2.3 | 结果区可见 OCR 文本和/或 JSON | ☐ |
| 2.4 | 顶部核心在线 / engine 信息 | ☐ |
| 2.5 | （建议）再试 `002_scan_like.png` 或 `003_cn_lyrics.png` | ☐ |

```powershell
curl.exe -X POST http://127.0.0.1:8765/v1/recognize -F "file=@samples/001_poc_digits.png"
```

---

## 3. 失败路径（DoD-4）

| # | 检查项 | 通过 |
|---|--------|------|
| 3.1 | core 未启动时 UI 有可读错误 | ☐ |
| 3.2 | 非 png/jpg 有格式提示 | ☐ |
| 3.3 | `.\scripts\stop.ps1` 后 health 不可达 | ☐ |

---

## 4. 联调闭环摘要

| 路径 | 组件 |
|------|------|
| 样例 | `samples/*.png` · 授权见 `samples/README.md` |
| UI | 导入 → 预览 → `POST /v1/recognize` |
| Base URL | `http://127.0.0.1:8765`（`VITE_ENPU_CORE_URL`） |
| 启停 | `start.ps1` / `stop.ps1` / `start.sh` / `stop.sh` |
| 冒烟 | `smoke-poc.ps1` |

---

## 5. 已知限制（非失败项）

| 限制 | 说明 |
|------|------|
| 精度 | Phase 0 不考核；合成样例 ≠ 真实印刷谱 |
| 样例版权 | 仅自制 CC0；勿提交未授权扫描件 |
| Paddle 首次 | 需下载模型，耗时与网络相关 |
| 平台 | PoC 以 Windows 为主 |
| Sidecar | 试验见 `docs/poc-sidecar.md`；正式集成 Phase 4 |

---

## 6. 结论

| 项 | 是 / 否 |
|----|---------|
| Milestone 1（桌面 PoC）验收通过 | ☐ |
| 样例与清单（#7）齐全可复现 | ☐ |
| 备注 | |

验收人：________　　日期：________
