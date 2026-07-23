# EnPu Core API

> 状态：约定草案。实现见 Issue #2 / #3；OpenAPI 以运行中的 `/docs` 为准。

**Base URL（开发态）**：`http://127.0.0.1:8765`

## GET `/health`

健康检查。

**响应** `200`

```json
{
  "status": "ok"
}
```

---

## POST `/v1/recognize`

上传一张简谱图片，返回识别结果。

**Content-Type**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | png / jpg / jpeg |

**响应** `200`（Phase 0 最小字段）

```json
{
  "ok": true,
  "engine": "paddleocr",
  "texts": ["1", "2", "3", "主", "恩"],
  "boxes": [],
  "notes": [],
  "meta": {
    "width": 0,
    "height": 0,
    "elapsed_ms": 0
  }
}
```

| 字段 | 说明 |
|------|------|
| `texts` | OCR 识别出的字符串列表 |
| `boxes` | 可选，检测框坐标 |
| `notes` | 可选，初级音高/结构（PoC 可为空） |
| `meta` | 图像尺寸、耗时等 |

**错误**

| HTTP | 说明 |
|------|------|
| `400` | 非图片或不支持格式 |
| `500` | 流水线/模型失败；`detail` 含可读信息 |

---

## 后续扩展（非 Phase 0）

- 异步任务：`POST /v1/jobs` + `GET /v1/jobs/{id}`  
- 导出：`POST /v1/export`（MusicXML / MIDI）  
- 鉴权：云端 API Key（Phase 3）  
