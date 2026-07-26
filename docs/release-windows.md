# Windows 安装包与 Sidecar 打包（Issue #14 / #81）

> 目标：在**没有安装 Python** 的 Windows 机器上，通过安装包运行 EnPu 桌面端，并由内置 `enpu-core` sidecar 完成本地基础识别（默认 **mock** 引擎）。

**默认安装包不含 PaddleOCR**。真识别需本机 Python + 安装后可选脚本，或开发态 venv。

---

## 0. 体积策略与实测（#81）

### 产品定位

```text
标准安装包 = Tauri UI + 轻量 core sidecar（mock OCR + OpenCV 结构/预处理 + music21 导出）
完整识别   = 可选后装：%LOCALAPPDATA%\EnPu\venv 或开发态 Paddle
```

| 项 | 说明 |
|----|------|
| 含什么 | 桌面 UI、`enpu-core.exe`（mock）、编辑/试听/导出 MusicXML·MIDI |
| 不含什么 | PaddlePaddle、PaddleOCR、OCR 模型、开发 samples/venv |
| 真 OCR | 安装包 post-install 脚本（需本机 Python）或 `.\scripts\start.ps1 -Engine paddleocr` |

### 基线 vs 瘦身后（本机 Windows 实测）

| 产物 | 瘦身前（约） | 瘦身后（#81，本机实测） | 备注 |
|------|-------------|-------------------------|------|
| `enpu-core.exe` | **~152 MB** | **~75 MB** | 主体积来源 |
| NSIS `*_x64-setup.exe` | **~154 MB** | **~77 MB** | **已低于 100 MB 目标** |
| 桌面主程序 | ~9 MB | ~9 MB | WebView2 系统自带 |

软预算（CI **警告**、不硬失败）：sidecar **>110 MB**、NSIS **>120 MB**。  
拉伸目标 NSIS **≤100 MB**：已达成（~77 MB）。再压需处理 Windows `cv2.pyd`（未压缩 ≈113 MB）。

### 体积分解（sidecar PKG 源文件，瘦身后）

| 组件 | 约占用 | 处理 |
|------|--------|------|
| `cv2` / OpenCV | ~113 MB（`cv2.pyd`） | **保留**（结构管线 / 预处理需要） |
| OpenCV FFmpeg DLL | 曾 ~60 MB | **剔除**（仅处理静态简谱图） |
| `scipy` + openblas | 曾 ~70 MB | **剔除**（music21 软依赖，导出不需要） |
| `matplotlib` 等 | 曾 ~15 MB+ | **剔除** |
| `numpy` + libs | ~27 MB | 保留 |
| music21 + 服务栈 | PYZ 等 | 保留最小导出路径；不 `collect_submodules` 全量 |
| Paddle / torch | — | **永不打进默认 sidecar** |

构建：`core/requirements-sidecar.txt` + `core/enpu-core.spec` 的 `excludes` / 二进制过滤。  
**不用 UPX**（误报与启动成本）。复现体积报告：

```powershell
.\scripts\build-core-sidecar.ps1
.\scripts\report-release-sizes.ps1
```

---

## 1. 架构

```text
EnPu.exe  (Tauri)
   │  启动时 spawn（若 8765 空闲）
   ▼
enpu-core.exe  (PyInstaller sidecar)
   │  http://127.0.0.1:8765
   ▼
/v1/recognize · /v1/export · /health
```

| 组件 | 说明 |
|------|------|
| 桌面 UI | Tauri 2 + React；发布态 `VITE_ENPU_CORE_URL=http://127.0.0.1:8765` |
| Sidecar | `core/dist/enpu-core.exe` → `desktop/src-tauri/binaries/enpu-core-<triple>.exe` |
| 默认引擎 | **mock**（体积可控、离线可冒烟） |
| 真实 OCR | 仍需开发态 venv + Paddle（见下文「已知限制」） |

---

## 2. 本机构建（可复现）

### 环境

| 工具 | 版本建议 |
|------|----------|
| Windows 10/11 x64 | — |
| Python 3.11/3.12 | core venv |
| Node.js 20+ | desktop |
| Rust stable + MSVC | `rustup` + VS C++ Build Tools |
| WebView2 | 系统通常已带 |

### 一键发布构建

```powershell
# 仓库根目录
.\scripts\build-release.ps1
# 或只打 NSIS、复用已有 sidecar：
.\scripts\build-release.ps1 -Targets nsis -SkipSidecarBuild
```

**打包前请关掉正在运行的 EnPu / enpu-core**（否则 NSIS 阶段会报 `os error 32` / 文件被占用）。  
`build-release.ps1` 会尝试自动结束这些进程；若仍失败：

```powershell
Get-Process enpu-desktop,enpu-core,EnPu -ErrorAction SilentlyContinue | Stop-Process -Force
.\scripts\build-release.ps1 -SkipSidecarBuild
```

步骤等价于：

```powershell
# 确保 Rust 在 PATH（新开终端后若找不到 cargo 请执行）
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"

.\scripts\build-core-sidecar.ps1          # → core/dist/enpu-core.exe
.\scripts\prepare-sidecar.ps1 -SkipBuild  # → src-tauri/binaries/enpu-core-x86_64-pc-windows-msvc.exe
cd desktop
$env:VITE_ENPU_CORE_URL = "http://127.0.0.1:8765"
npm ci
# 注意：`--` 必须有，否则 npm 可能吃掉 --bundles，导致不生成 target/release
npm run tauri -- build --bundles nsis
```

产物应出现：

```text
desktop/src-tauri/target/release/enpu-desktop.exe
desktop/src-tauri/target/release/bundle/nsis/EnPu_*_x64-setup.exe
```

### 产物位置

```text
desktop/src-tauri/target/release/bundle/nsis/EnPu_*_x64-setup.exe
desktop/src-tauri/target/release/EnPu.exe          # 便携主程序（同目录需有 sidecar 资源）
```

安装包文件名随 `tauri.conf.json` 的 `version` 变化。

---

## 3. 目标机验收（无 Python）

1. 运行 NSIS 安装包（当前用户安装，无需管理员）  
2. 启动 **EnPu**  
3. 标题栏/状态应能连上核心（自动拉起 sidecar）  
4. 导入 `samples/001_poc_digits.png`（安装后可从仓库或发行包附带样例）  
5. 点击识别 → mock 引擎返回固定/样例 OCR 文本  
6. 编辑 / 试听 / 导出 JSON（MusicXML 依赖 sidecar 内 music21）  

若 8765 已被占用（例如本机 dev core），桌面**不会**重复拉起 sidecar，而是复用已有服务。

---

## 4. CI / CD 流水线

| Workflow | 触发 | 作用 |
|----------|------|------|
| `.github/workflows/ci.yml` | push/PR → main | Linux：core pytest + desktop vite build |
| **`.github/workflows/cd-windows.yml`** | **手动** 或 **tag `v*`** | **CD：Windows NSIS 安装包 + sidecar artifact**（可选 GitHub Release） |

### 手动 CD（推荐）

```text
GitHub → Actions → CD Windows → Run workflow
```

| 输入 | 说明 |
|------|------|
| `create_release` | 勾选则额外创建/更新 GitHub Release（无 tag 时为 draft） |
| `release_tag` | 可选；`create_release` 且无 git tag 时使用，如 `v0.1.0-rc1` |

构建产物在 run 的 **Artifacts** 中下载（`EnPu-windows-<version>-<sha>`）：

- `EnPu_*_x64-setup.exe` — NSIS 安装包  
- `enpu-core.exe` — mock sidecar  
- `SHA256SUMS.txt`  

### Tag 发布（正式版）

```bash
git tag v0.1.0
git push origin v0.1.0
```

会自动跑 **CD Windows**，并把安装包挂到该 tag 的 GitHub Release。

---

## 5. 已知限制

1. **默认 mock OCR**：安装包为「UI + 瘦身 sidecar（约 75MB）」，**不含** PaddleOCR 模型。真实拍照识别：  
   - 开发态：`.\scripts\start.ps1 -Engine paddleocr`  
   - 安装后：本机 Python 3.10+ + post-install / `%LOCALAPPDATA%\EnPu\venv`  
2. **无控制台 sidecar 日志**：`enpu-core.exe` 为 windowed 构建时日志写入同目录 `enpu-core.log`（避免 uvicorn `isatty` 崩溃）。  
3. **关闭桌面时询问是否结束 enpu-core**（进程树 `taskkill /T`，避免 PyInstaller 残留）。  
4. **安装后 PaddleOCR**：NSIS `NSIS_HOOK_POSTINSTALL` 运行 `resources/install-paddle-ocr.ps1`，在 `%LOCALAPPDATA%\EnPu\venv` 安装 Paddle；成功后生成 `start-enpu-core-paddle.cmd`，桌面优先用真实 OCR。  
5. **首次 Paddle**：若自行改 sidecar 打入 paddle，体积与路径问题见 [poc-sidecar.md](./poc-sidecar.md)。  
6. **杀软误报**：PyInstaller onefile 偶发误报；**未使用 UPX**（#81）。  
7. **签名**：当前未做 Authenticode 代码签名；企业分发需自行签名。  
8. **macOS/Linux 安装包**：#14 仅 Windows。  
9. **剩余体积瓶颈**：Windows wheel 的 `cv2.pyd` 很大；再压到极致需自建 OpenCV 或换轻量 CV 栈（另开 Issue）。  

---

## 6. 验收勾选

### #14 安装闭环

- [x] 可复现脚本：`scripts/build-release.ps1` + `prepare-sidecar.ps1`  
- [x] Tauri `externalBin` + 应用生命周期内 start/stop sidecar  
- [x] 默认无 Python 可完成 **mock 识别闭环**  
- [x] CI workflow 可构建 Windows 安装产物（Actions artifact）  
- [ ] （人工）在干净 Windows 机安装 NSIS 包点验  

### #81 瘦身

- [x] 书面体积分解（上文 §0）  
- [x] sidecar 默认依赖与 `excludes` 裁剪（`requirements-sidecar.txt` + `enpu-core.spec`）  
- [x] 本机 sidecar **~152 → ~75 MB**；NSIS **~154 → ~77 MB**（mock 识别 / MusicXML·MIDI 导出冒烟）  
- [x] CD 打印/归档 `SIZE_REPORT.txt`；>110 / >120 MB 仅 warning  
- [x] 文档明确默认不含 PaddleOCR  
- [ ] （可选）OCR 附加组件按需下载 — 另开 Issue  

---

## 7. 相关文件

| 路径 | 说明 |
|------|------|
| `core/enpu-core.spec` | PyInstaller（#81 精简 excludes / 去 FFmpeg） |
| `core/requirements-sidecar.txt` | 发布 sidecar 依赖（无 Paddle） |
| `core/requirements-ci.txt` | CI pytest（无 Paddle） |
| `scripts/build-core-sidecar.ps1` | 打 sidecar（默认 sidecar 依赖） |
| `scripts/report-release-sizes.ps1` | 体积报告 |
| `scripts/prepare-sidecar.ps1` | 拷贝为 triple 名 |
| `scripts/build-release.ps1` | 全量发布构建 |
| `desktop/src-tauri/src/lib.rs` | sidecar 生命周期 |
| `desktop/src-tauri/tauri.conf.json` | `externalBin` + NSIS |
| `.github/workflows/cd-windows.yml` | CD + size soft budgets |
