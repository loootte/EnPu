# Sidecar binaries (Tauri externalBin)

Tauri 2 expects platform-suffixed names:

```text
enpu-core-x86_64-pc-windows-msvc.exe
```

**Do not commit large binaries** (gitignored). Generate locally or in CI:

```powershell
# from repo root
.\scripts\build-core-sidecar.ps1
.\scripts\prepare-sidecar.ps1 -SkipBuild
```

Or full release:

```powershell
.\scripts\build-release.ps1
```

Configured in `tauri.conf.json` as `"externalBin": ["binaries/enpu-core"]`.
