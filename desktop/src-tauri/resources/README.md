# Bundled resources (installer)

| File | Purpose |
|------|---------|
| `install-paddle-ocr.ps1` | Post-install PaddleOCR setup → `%LOCALAPPDATA%\EnPu` |
| `enpu-core-src/` | Copy of `core/app` + `run_server.py` for the paddle launcher |

Generate `enpu-core-src` before `tauri build`:

```powershell
.\scripts\prepare-core-app-resources.ps1
```

(`build-release.ps1` runs this automatically.)
