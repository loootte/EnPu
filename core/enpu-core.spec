# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for EnPu core sidecar (Phase 0 / issue #8 PoC).
# Default build targets mock engine for a manageable binary.
# Full PaddleOCR bundling is documented as deferred (size + native deps).

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden = []
# Collect FastAPI / starlette / pydantic plugins lightly
for pkg in ("uvicorn", "anyio", "starlette", "fastapi", "pydantic", "pydantic_settings"):
    try:
        hidden += collect_submodules(pkg)
    except Exception:
        pass

a = Analysis(
    ["run_server.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden
    + [
        "app",
        "app.main",
        "app.config",
        "app.api",
        "app.api.v1",
        "app.api.v1.recognize",
        "app.pipeline",
        "app.pipeline.runner",
        "app.pipeline.preprocess",
        "app.pipeline.ocr",
        "app.pipeline.parse",
        "app.schemas",
        "app.schemas.recognize",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "multipart",
        "PIL",
        "cv2",
        "numpy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Keep paddle out of the PoC sidecar unless explicitly rebuilt with OCR extras.
        "paddle",
        "paddleocr",
        "paddlepaddle",
        "skimage",
        "matplotlib",
        "scipy",
        "torch",
        "tensorflow",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="enpu-core",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # sidecar is a headless server; console helps debugging first runs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
