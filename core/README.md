# EnPu Core — 识别核心

Python **FastAPI** 服务：图像预处理（OpenCV）→ OCR（PaddleOCR）→ 结构化 / 导出（music21）。

桌面端与云端共用本目录代码。

## 目录

```text
core/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py
│   ├── api/v1/recognize.py  # 识别接口
│   ├── pipeline/            # 预处理 / OCR / 解析 / 导出
│   └── schemas/             # Pydantic 模型
├── tests/
├── requirements.txt
├── Dockerfile
└── README.md
```

## 开发启动（目标命令）

```powershell
cd core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

或在仓库根目录：

```powershell
.\scripts\dev-core.ps1
```

- 健康检查：http://127.0.0.1:8765/health  
- Swagger：http://127.0.0.1:8765/docs  

## 实现状态

| 能力 | Issue | 状态 |
|------|-------|------|
| FastAPI 骨架 + mock recognize | [#2](https://github.com/loootte/EnPu/issues/2) | 待实现 |
| OpenCV + PaddleOCR 流水线 | [#3](https://github.com/loootte/EnPu/issues/3) | 待实现 |
| JSON Schema / 解析 / 导出 | #9–#11 | 后续阶段 |

脚手架已就位；可运行服务请跟进上述 Issue。

## 依赖说明

正式依赖列表在 `requirements.txt` 中随 #2 补全。预期包括：

- `fastapi` / `uvicorn`  
- `opencv-python-headless`  
- `paddlepaddle` + `paddleocr`（体积较大，首次运行会下载模型）  
- `music21`（导出阶段）  
- `python-multipart`（上传文件）  
