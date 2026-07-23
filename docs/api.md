# EnPu Core API

> 状态：#2–#3 识别流水线 + #9–#10 Score 解析 + #11 MusicXML/MIDI 导出。OpenAPI 以运行中的 `/docs` 为准。

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

---

## POST `/v1/export`

将 **EnPu Score v0.1 JSON** 导出为 MusicXML 或 MIDI（Issue [#11](https://github.com/loootte/EnPu/issues/11)）。

**Content-Type**：`application/json`（body = 完整 `Score` 文档）

| Query | 类型 | 默认 | 说明 |
|-------|------|------|------|
| `format` | `musicxml` \| `midi` | `musicxml` | 导出格式 |
| `download` | bool | `false` | `true` 时返回原始文件字节（带 `Content-Disposition`） |

**响应** `200`（`download=false`，默认）

```json
{
  "ok": true,
  "format": "musicxml",
  "filename": "示例诗歌_最小_.musicxml",
  "media_type": "application/vnd.recordare.musicxml+xml",
  "content_base64": "PD94bWwg...",
  "byte_length": 4321,
  "warnings": []
}
```

| 字段 | 说明 |
|------|------|
| `content_base64` | 文件内容的 Base64（UI 可直接保存） |
| `media_type` | MusicXML 或 `audio/midi` |
| `warnings` | 导出告警（如未知调号回退到 C） |

**响应** `200`（`download=true`）

- MusicXML：`application/vnd.recordare.musicxml+xml` 原始 XML  
- MIDI：`audio/midi`，文件头 `MThd`  

**错误**

| HTTP | 说明 |
|------|------|
| `400` | 无声部 / 无音符 / 非法 Score |
| `422` | body 不符合 Score schema |
| `500` | 未安装 music21 或写出失败 |

**示例**

```powershell
# JSON + base64
curl.exe -X POST "http://127.0.0.1:8765/v1/export?format=musicxml" `
  -H "Content-Type: application/json" `
  --data-binary "@samples/scores/example-minimal.json"

# 直接下载 MIDI 文件
curl.exe -X POST "http://127.0.0.1:8765/v1/export?format=midi&download=true" `
  -H "Content-Type: application/json" `
  --data-binary "@samples/scores/example-minimal.json" `
  -o out.mid
```

> 识别接口 `/v1/recognize` 返回的 `score` 可原样 POST 到本接口完成「识别 → 导出」链路。

---

## 后续扩展

- 异步任务与云端鉴权（Phase 3）  
- 桌面端一键导出 UI（#12）  
