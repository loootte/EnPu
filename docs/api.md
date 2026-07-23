# EnPu Core API

> 状态：#2 骨架 + #3 OpenCV/PaddleOCR 流水线。OpenAPI 以运行中的 `/docs` 为准。

**Base URL（开发态）**：`http://127.0.0.1:8765`

## GET `/health`

**响应** `200`

```json
{
  "status": "ok",
  "version": "0.0.2",
  "engine": "paddleocr"
}
```

`engine` 为当前配置的识别引擎名（`paddleocr` 或 `mock`）。

---

## POST `/v1/recognize`

上传一张简谱图片，返回识别结果。

**Content-Type**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | png / jpg / jpeg |

**响应** `200`

```json
{
  "ok": true,
  "engine": "paddleocr",
  "texts": ["1  2  3  |  5  -  -", "主 恩 典"],
  "boxes": [
    { "x1": 10.0, "y1": 20.0, "x2": 40.0, "y2": 50.0, "score": 0.98 }
  ],
  "notes": [
    { "pitch": "1", "text": "1  2  3  |  5  -  -", "extra": { "source": "ocr_digit" } }
  ],
  "score": {
    "schema_version": "0.1",
    "title": "",
    "key": "C",
    "time_signature": "4/4",
    "parts": [{ "id": "P1", "name": "melody", "measures": [] }]
  },
  "meta": {
    "width": 640,
    "height": 280,
    "elapsed_ms": 1234,
    "filename": "001_poc_digits.png",
    "content_type": "image/png",
    "mock": false,
    "preprocess_steps": ["decode", "grayscale", "bilateral_denoise", "to_bgr"],
    "scale": 1.0,
    "item_count": 5,
    "parse_mode": "score",
    "parse_warnings": []
  }
}
```

| 字段 | 说明 |
|------|------|
| `engine` | `paddleocr` 或 `mock` |
| `texts` | OCR 字符串列表 |
| `boxes` | 检测框（轴对齐） |
| `notes` | 轻量音高提示（`1`–`7`） |
| `score` | EnPu Score v0.1（#9/#10）；解析失败时为 `null` |
| `meta.parse_mode` | `score` \| `hints` \| `ocr_only` |
| `meta.parse_warnings` | 解析告警（不阻塞请求） |
| `meta.preprocess_steps` | OpenCV 预处理步骤 |
| `meta.mock` | 是否 mock 引擎 |

**错误**

| HTTP | 说明 |
|------|------|
| `400` | 空文件、非图片、不支持格式、超过大小限制 |
| `422` | 缺少 `file` |
| `500` | OCR 引擎未安装 / 初始化或推理失败 |

**环境**

- `ENPU_RECOGNIZE_ENGINE=mock`：不加载 Paddle，返回固定 mock 文本  
- 默认 `paddleocr`：首次运行下载模型  

---

## 后续扩展

- 完整简谱结构化（#9–#10）  
- MusicXML / MIDI 导出（#11）  
- 异步任务与云端鉴权（Phase 3）  
