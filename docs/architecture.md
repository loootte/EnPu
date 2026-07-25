# EnPu 架构说明

> 状态：脚手架文档（Phase 0）。随实现迭代更新。

## 1. 目标架构

EnPu 将 **识别核心** 与 **桌面 UI** 解耦：

- **core**：Python FastAPI 服务，负责图像预处理、OCR、简谱结构化与导出  
- **desktop**：Tauri 2 桌面应用，负责导入、预览、结果展示与后续编辑  
- 通信：HTTP JSON（开发态 `http://127.0.0.1:8765`；发布态可为 sidecar 或云端）

```text
[用户] → [desktop UI]
              │  multipart 图片 / JSON
              ▼
         [core FastAPI]
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
 preprocess   OCR     parse/export
 (OpenCV) (PaddleOCR) (规则/music21)
```

### 结构优先路径（#58，可选）

默认 `ENPU_PIPELINE_MODE=legacy`（整页 OCR → parse）。设为 `structure` 时采用**结构优先、OCR 托底**分层：

```text
L1  页面级
    ├── 标题
    ├── 调号 / 拍号
    └── 主谱面（score region）

L2  主谱面
    └── 谱行 systems（旋律数字 + 和弦 + 歌词绑定为同一逻辑行）

L3  谱行
    └── 小节 measures（小节线切分；Score 小节权威来源）

L4  小节内
    ├── 音符候选 ROI（pitch）
    ├── 和弦 / 歌词候选（独立 kind）
    └── 小节线（可视化）

L5  音符节点
    ├── 音高数字          ← 主要 OCR 位置（可有几何兜底）
    ├── 时值线（下划线）
    ├── 高低音点 / 附点 / 延音线（几何，持续完善）
    └── → 组装 Score JSON
```

原则：**L1–L4 以 OpenCV / 几何为主；L5 对局部 ROI 做音高 OCR 并绑定几何特征。**

流水线：`preprocess → L1 → L2 → L3 → L4 → L5 → assemble Score`。

详见 [architecture-structure-first.md](./architecture-structure-first.md)。

## 2. 部署形态

| 形态 | 说明 | 阶段 |
|------|------|------|
| 开发双进程 | 手动启 core + `tauri dev` | Phase 0（默认） |
| 本地 sidecar | PyInstaller 打包 core，由 Tauri 拉起 | Phase 0 可选 / Phase 4 |
| 云端 | Docker 部署同一 core，UI 切换 Endpoint | Phase 3 |

## 3. 目录职责

| 路径 | 职责 |
|------|------|
| `core/app/main.py` | FastAPI 应用入口 |
| `core/app/api/v1/` | 版本化 HTTP 接口 |
| `core/app/pipeline/` | 预处理 / OCR / 解析 / 导出 |
| `core/app/schemas/` | 请求/响应与 EnPu JSON 模型 |
| `desktop/src/` | React UI |
| `desktop/src-tauri/` | Tauri 原生壳 |
| `samples/` | 公开样例图 |
| `deploy/` | 容器与编排 |

## 4. 核心 API（约定）

完整字段见 [api.md](./api.md)。Phase 0 最小集：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/v1/recognize` | 上传图片，返回 OCR / 结构结果 |

## 5. 数据真相源

- **内部**：EnPu JSON **Score v0.1**（[jianpu-schema.md](./jianpu-schema.md)，Pydantic `app.schemas.score.Score`）  
- **导出**：MusicXML / MIDI 由 core 从 Score 生成，不反向作为主存储  
- **OCR 层**：`RecognizeResponse` 为原始识别；解析后应落到 `Score`（#10）  

## 6. 非目标（Phase 0）

- 高精度结构识别  
- 账号体系与多人协作  
- macOS / Linux 打包  

## 7. 相关文档

- 产品与阶段计划：[ROADMAP.md](../ROADMAP.md)  
- 核心模块：[core/README.md](../core/README.md)  
- 桌面模块：[desktop/README.md](../desktop/README.md)  
