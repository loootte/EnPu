# EnPu Core API

> 状态：#2 已实现 `/health` 与 mock `/v1/recognize`。OpenAPI 以运行中的 `/docs` 为准。

**Base URL（开发态）**：`http://127.0.0.1:8765`

## GET `/health`

健康检查。

**响应** `200`

```json
{
  "status": "ok",
  "version": "0.0.1"
}
```

---

## POST `/v1/recognize`

上传一张简谱图片，返回识别结果。

**Content-Type**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | png / jpg / jpeg |

**响应** `200`（Phase 0）

```json
{
  "ok": true,
  "engine": "mock",
  "texts": ["1", "2", "3", "主", "恩"],
  "boxes": [],
  "notes": [],
  "meta": {
    "width": 40,
    "height": 30,
    "elapsed_ms": 2,
    "filename": "sample.png",
    "content_type": "image/png",
    "mock": true
  }
}
```

| 字段 | 说明 |
|------|------|
| `engine` | 当前引擎：`mock`（#2）；#3 起可为 `paddleocr` |
| `texts` | OCR 识别字符串列表（mock 为固定示例） |
| `boxes` | 检测框（mock 为空数组） |
| `notes` | 初级结构（mock 为空；Schema 见 #9） |
| `meta` | 图像尺寸、耗时、是否 mock 等 |

**错误**

| HTTP | 说明 |
|------|------|
| `400` | 空文件、非图片、不支持格式、超过大小限制 |
| `422` | 缺少 `file` 字段 |
| `500` | 流水线/模型失败（真实 OCR 阶段） |

---

## 后续扩展（非 Phase 0）

- 真实 OCR 流水线（#3）  
- 异步任务：`POST /v1/jobs` + `GET /v1/jobs/{id}`  
- 导出：`POST /v1/export`（MusicXML / MIDI）  
- 鉴权：云端 API Key（Phase 3）  
