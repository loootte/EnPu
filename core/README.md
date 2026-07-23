# EnPu Core — 识别核心

Python **FastAPI** 服务：图像预处理（OpenCV）→ OCR（PaddleOCR）→ 结构化 / 导出（music21）。

桌面端与云端共用本目录代码。

## 目录

```text
core/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 环境变量配置（ENPU_*）
│   ├── api/v1/recognize.py  # 识别接口
│   ├── pipeline/            # 预处理 / OCR / 解析 / 导出（#3+）
│   └── schemas/             # Pydantic 模型
├── tests/
├── requirements.txt
├── pytest.ini
├── Dockerfile
└── README.md
```

## 开发启动

```powershell
cd core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

或在仓库根目录（自动创建 venv 并安装依赖）：

```powershell
.\scripts\dev-core.ps1
```

| URL | 说明 |
|-----|------|
| http://127.0.0.1:8765/health | 健康检查 |
| http://127.0.0.1:8765/docs | OpenAPI Swagger |
| http://127.0.0.1:8765/v1/recognize | 上传图片识别（当前为 **mock**） |

### 手动试调 recognize

```powershell
curl -Method POST -Uri http://127.0.0.1:8765/v1/recognize `
  -Form "file=@..\samples\your.png"
```

## 运行测试

```powershell
cd core
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
```

## 环境变量（可选）

| 变量 | 默认 | 说明 |
|------|------|------|
| `ENPU_HOST` | `127.0.0.1` | 绑定地址（脚本侧使用） |
| `ENPU_PORT` / `ENPU_CORE_PORT` | `8765` | 端口 |
| `ENPU_CORS_ORIGINS` | `*` | CORS，逗号分隔 |
| `ENPU_RECOGNIZE_ENGINE` | `mock` | `mock`（#3 将接 `paddleocr`） |
| `ENPU_MAX_UPLOAD_BYTES` | `20971520` | 最大上传 20MiB |

## 实现状态

| 能力 | Issue | 状态 |
|------|-------|------|
| FastAPI 骨架 + mock recognize | [#2](https://github.com/loootte/EnPu/issues/2) | **已实现** |
| OpenCV + PaddleOCR 流水线 | [#3](https://github.com/loootte/EnPu/issues/3) | 待实现 |
| JSON Schema / 解析 / 导出 | #9–#11 | 后续阶段 |

## 依赖

见 `requirements.txt`。当前 Phase 0 轻量依赖：FastAPI / Uvicorn / Pillow / Pydantic。

OpenCV、PaddleOCR、music21 在后续 Issue 引入（体积与安装成本较高）。
