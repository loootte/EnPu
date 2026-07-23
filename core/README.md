# EnPu Core — 识别核心

Python **FastAPI** 服务：图像预处理（OpenCV）→ OCR（PaddleOCR）→ 结构化 / 导出（music21）。

桌面端与云端共用本目录代码。

## 目录

```text
core/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/v1/recognize.py
│   ├── pipeline/
│   │   ├── preprocess.py   # OpenCV
│   │   ├── ocr.py          # PaddleOCR / mock
│   │   ├── parse.py        # 数字音高初提取
│   │   └── runner.py       # 端到端编排
│   └── schemas/
├── tests/
├── requirements.txt
└── README.md
```

## 开发启动

```powershell
cd core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# 首次使用 PaddleOCR 会下载模型，请保持网络畅通
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

或在仓库根目录：

```powershell
.\scripts\dev-core.ps1
```

| URL | 说明 |
|-----|------|
| http://127.0.0.1:8765/health | 健康检查（含当前 engine） |
| http://127.0.0.1:8765/docs | OpenAPI |
| http://127.0.0.1:8765/v1/recognize | 上传图片识别 |

### 试调样例

```powershell
# 默认引擎 paddleocr（真实 OCR）
curl.exe -X POST "http://127.0.0.1:8765/v1/recognize" `
  -F "file=@..\samples\001_poc_digits.png"

# 离线 mock（不加载 Paddle）
$env:ENPU_RECOGNIZE_ENGINE = "mock"
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

## 运行测试

```powershell
cd core
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
# 可选：真实 OCR 集成（慢，需已装 Paddle 与模型）
# $env:ENPU_TEST_REAL_OCR = "1"
# $env:ENPU_RECOGNIZE_ENGINE = "paddleocr"
# pytest -k real_ocr
```

单元测试默认 `ENPU_RECOGNIZE_ENGINE=mock`，不依赖 Paddle 模型。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `ENPU_RECOGNIZE_ENGINE` | `paddleocr` | `paddleocr` 或 `mock` |
| `ENPU_OCR_LANG` | `ch` | PaddleOCR 语言 |
| `ENPU_OCR_USE_ANGLE_CLS` | `true` | 方向分类 |
| `ENPU_OCR_USE_GPU` | `false` | GPU（需对应 paddle 包） |
| `ENPU_OCR_MAX_SIDE` | `2000` | 预处理最长边缩放 |
| `ENPU_OCR_DENOISE` | `true` | 双边滤波去噪 |
| `ENPU_MAX_UPLOAD_BYTES` | `20971520` | 最大上传 |
| `ENPU_CORS_ORIGINS` | `*` | CORS |

## 流水线说明（#3）

1. **decode** — OpenCV `imdecode`  
2. **resize** — 长边超过 `ENPU_OCR_MAX_SIDE` 时缩小  
3. **grayscale + denoise** — 灰度 + 可选 bilateral  
4. **PaddleOCR** — 整图检测识别 → `texts` + `boxes`  
5. **parse** — OCR → `Score` v0.1（音高/时值/小节；失败回退 hints / ocr_only）

> 识别精度不是 Phase 0 目标；先打通链路。

## Sidecar 打包（可选，Issue #8）

```powershell
# 仓库根目录
.\scripts\build-core-sidecar.ps1
.\core\dist\enpu-core.exe --engine mock --port 8765
```

试验记录：`docs/poc-sidecar.md`。

## 实现状态

| 能力 | Issue | 状态 |
|------|-------|------|
| FastAPI 骨架 + mock recognize | #2 | 已实现 |
| OpenCV + PaddleOCR 最小流水线 | #3 | 已实现 |
| PyInstaller sidecar / 一键启停试验 | #8 | 已记录 |
| Score Schema v0.1 | #9 | 已实现 |
| OCR → Score 解析 MVP | #10 | **已实现** |
| music21 导出 MusicXML/MIDI | #11 | 后续 |

## Paddle 安装说明

`paddlepaddle` / `paddleocr` 体积较大，且与 Python 小版本、CPU/GPU 相关。

若 `pip install -r requirements.txt` 失败，可先装 API 依赖，再单独装 Paddle：

```powershell
pip install fastapi "uvicorn[standard]" python-multipart pydantic pydantic-settings Pillow numpy opencv-python-headless
# 参见 https://www.paddlepaddle.org.cn/install/quick
pip install paddlepaddle
pip install "paddleocr>=2.7,<3"
```

首次调用 `/v1/recognize`（engine=paddleocr）会下载检测/识别模型，请预留磁盘与时间。
