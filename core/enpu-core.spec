# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for EnPu core sidecar (#8 / #14 / #81).
#
# Default build: mock OCR + OpenCV preprocess/structure + music21 export.
# Intentionally excludes PaddleOCR / torch and heavy optional stacks that
# music21 soft-imports (scipy, matplotlib, networkx, …).
#
# Size notes (see docs/release-windows.md § size breakdown):
#   - cv2.pyd is the largest unavoidable binary (~100MB+ on Windows wheels)
#   - opencv videoio FFmpeg DLLs are stripped (we only process still images)
#   - do NOT collect_submodules("music21") — that pulls half of PyPI

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Minimal server stack only (avoid full package walks that drag tests/extras).
hidden = []
for pkg in (
    "uvicorn",
    "anyio",
    "starlette",
    "fastapi",
    "pydantic",
    "pydantic_settings",
):
    try:
        # Filter out tests / typing plugins that inflate the archive
        hidden += collect_submodules(
            pkg,
            filter=lambda name: not any(
                part in name
                for part in (
                    ".tests",
                    ".testing",
                    "pytest",
                    "mypy",
                    "py.typed",
                )
            ),
        )
    except Exception:
        pass

# music21: only modules needed for Score → MusicXML / MIDI export.
# Full collect_submodules("music21") also pulls analysis/corpus/tests and
# soft-deps scipy/matplotlib/networkx (~80MB+).
_MUSIC21_HIDDEN = [
    "music21",
    "music21.base",
    "music21.chord",
    "music21.clef",
    "music21.common",
    "music21.converter",
    "music21.duration",
    "music21.dynamics",
    "music21.environment",
    "music21.exceptions21",
    "music21.expressions",
    "music21.interval",
    "music21.key",
    "music21.layout",
    "music21.metadata",
    "music21.meter",
    "music21.note",
    "music21.pitch",
    "music21.repeat",
    "music21.roman",
    "music21.scale",
    "music21.spanner",
    "music21.stream",
    "music21.stream.base",
    "music21.stream.core",
    "music21.stream.filters",
    "music21.stream.iterator",
    "music21.stream.makeNotation",
    "music21.style",
    "music21.tempo",
    "music21.tie",
    "music21.volume",
    "music21.musicxml",
    "music21.musicxml.m21ToXml",
    "music21.musicxml.xmlObjects",
    "music21.musicxml.xmlHelpers",
    "music21.musicxml.partStaffExporter",
    "music21.midi",
    "music21.midi.translate",
    "music21.midi.base",
]

a = Analysis(
    ["run_server.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden
    + _MUSIC21_HIDDEN
    + [
        "app",
        "app.main",
        "app.config",
        "app.api",
        "app.api.v1",
        "app.api.v1.recognize",
        "app.api.v1.export",
        "app.api.v1.preprocess",
        "app.pipeline",
        "app.pipeline.runner",
        "app.pipeline.preprocess",
        "app.pipeline.ocr",
        "app.pipeline.parse",
        "app.pipeline.barlines",
        "app.pipeline.export",
        "app.pipeline.layout",
        "app.pipeline.crop_merge",
        "app.pipeline.problems",
        "app.pipeline.duration",
        "app.pipeline.structure",
        "app.pipeline.structure.pipeline",
        "app.pipeline.structure.assemble",
        "app.pipeline.structure.rebuild",
        "app.pipeline.structure.ir",
        "app.pipeline.structure.l1_page",
        "app.pipeline.structure.l2_systems",
        "app.pipeline.structure.l3_measures",
        "app.pipeline.structure.l4_notes",
        "app.pipeline.structure.l5_glyph",
        "app.schemas",
        "app.schemas.recognize",
        "app.schemas.score",
        "app.schemas.export",
        "app.schemas.preprocess",
        "app.schemas.problems",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "multipart",
        "PIL",
        "PIL.Image",
        "cv2",
        "numpy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # OCR stacks (install post-hoc if needed)
        "paddle",
        "paddleocr",
        "paddlepaddle",
        "paddlex",
        "torch",
        "torchvision",
        "tensorflow",
        "onnxruntime",
        "skimage",
        "sklearn",
        "pandas",
        # music21 soft / optional deps — not needed for export path
        "scipy",
        "scipy.libs",
        "matplotlib",
        "matplotlib.backends",
        "mpl_toolkits",
        "networkx",
        "joblib",
        "numba",
        "llvmlite",
        "sympy",
        "IPython",
        "jupyter",
        "notebook",
        "ipykernel",
        "pygments",
        # GUI / tests / build tools
        "tkinter",
        "_tkinter",
        "turtle",
        "pytest",
        "_pytest",
        # music21 imports stdlib unittest at runtime — keep it
        "Cython",
        "cython",
        # Unused server extras (uvicorn[standard] may still be installed)
        "watchfiles",
        "watchgod",
        "websockets",
        "wsproto",
        "httptools",
        "uvloop",
        # Other heavy optional
        "pymupdf",
        "fitz",
        "lxml.html.clean",
        "bs4",
        "beautifulsoup4",
        "selenium",
        "cv2.gapi",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)


def _keep_binary(entry) -> bool:
    """Drop FFmpeg video codecs and Tk/Tcl (still-image + headless server only)."""
    name = entry[0].replace("\\", "/").lower()
    drop_tokens = (
        "ffmpeg",
        "opencv_videoio_ffmpeg",
        "tk86",
        "tcl86",
        "_tkinter",
        "/_tcl_data",
        "/_tk_data",
        "tcl/tcl8",
        "tk/tk8",
    )
    return not any(t in name for t in drop_tokens)


def _keep_data(entry) -> bool:
    name = entry[0].replace("\\", "/").lower()
    drop_tokens = (
        "_tcl_data",
        "_tk_data",
        "tcl8",
        "tk8",
        "matplotlib",
        "scipy",
        "music21/corpus",
        "music21/test",
        "music21/alpha",
    )
    return not any(t in name for t in drop_tokens)


a.binaries = [b for b in a.binaries if _keep_binary(b)]
a.datas = [d for d in a.datas if _keep_data(d)]
# Also drop pure modules that slipped past excludes via hooks
_drop_pure_prefixes = (
    "scipy",
    "matplotlib",
    "networkx",
    "joblib",
    "IPython",
    "pytest",
    "_pytest",
    "Cython",
    "tkinter",
    "watchfiles",
    "websockets",
    "httptools",
    "pygments",
    "pymupdf",
    "fitz",
)


def _keep_pure(mod) -> bool:
    name = mod[0] if isinstance(mod, (tuple, list)) else str(mod)
    return not any(name == p or name.startswith(p + ".") for p in _drop_pure_prefixes)


a.pure = [m for m in a.pure if _keep_pure(m)]

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
    upx=False,  # UPX ↑ false-positive rate; keep off for #81
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=False hides server window in production desktop package
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
