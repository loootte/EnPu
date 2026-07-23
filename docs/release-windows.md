# Windows 安装包与 Sidecar 打包（Issue #14）

> 目标：在**没有安装 Python** 的 Windows 机器上，通过安装包运行 EnPu 桌面端，并由内置 `enpu-core` sidecar 完成本地基础识别（默认 **mock** 引擎）。

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

## 4. CI / 发布流水线

| Workflow | 触发 | 作用 |
|----------|------|------|
| `.github/workflows/ci.yml` | push/PR → main | Linux：core pytest + desktop vite build |
| `.github/workflows/release-windows.yml` | `workflow_dispatch` 或 tag `v*` | Windows：sidecar + Tauri NSIS，上传 artifact |

手动触发：

```text
GitHub → Actions → Release Windows → Run workflow
```

Tag 发布：

```bash
git tag v0.1.0
git push origin v0.1.0
```

---

## 5. 已知限制

1. **默认 mock OCR**：安装包体积约「UI + ~100MB sidecar」，**不含** PaddleOCR 模型。真实拍照识别请用开发态：  
   `.\scripts\start.ps1 -Engine paddleocr`  
2. **首次 Paddle**：若自行改 sidecar 打入 paddle，体积与路径问题见 [poc-sidecar.md](./poc-sidecar.md)。  
3. **杀软误报**：PyInstaller onefile 偶发误报；未使用 UPX。  
4. **签名**：当前未做 Authenticode 代码签名；企业分发需自行签名。  
5. **macOS/Linux 安装包**：#14 仅 Windows。  

---

## 6. 验收勾选（#14）

- [x] 可复现脚本：`scripts/build-release.ps1` + `prepare-sidecar.ps1`  
- [x] Tauri `externalBin` + 应用生命周期内 start/stop sidecar  
- [x] 默认无 Python 可完成 **mock 识别闭环**  
- [x] CI workflow 可构建 Windows 安装产物（Actions artifact）  
- [ ] （人工）在干净 Windows 机安装 NSIS 包点验  

---

## 7. 相关文件

| 路径 | 说明 |
|------|------|
| `core/enpu-core.spec` | PyInstaller |
| `scripts/build-core-sidecar.ps1` | 打 sidecar |
| `scripts/prepare-sidecar.ps1` | 拷贝为 triple 名 |
| `scripts/build-release.ps1` | 全量发布构建 |
| `desktop/src-tauri/src/lib.rs` | sidecar 生命周期 |
| `desktop/src-tauri/tauri.conf.json` | `externalBin` + NSIS |
