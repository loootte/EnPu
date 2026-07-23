# 样例简谱（samples）

本目录存放 **可公开** 的中文敬拜风格简谱样例图，用于：

- 开发与回归（OpenCV / OCR / UI 预览）
- PoC 验收（见 [docs/poc-acceptance.md](../docs/poc-acceptance.md)）
- `scripts/smoke-poc.ps1` 默认样例

## 版权与授权

| 规则 | 说明 |
|------|------|
| **仅自制 / 公有领域 / 已授权** | 禁止提交未授权的商业诗歌谱面扫描件 |
| **本仓库样例** | 全部由程序绘制（OpenCV / Pillow），**不包含**任何真实出版乐谱的扫描件 |
| **授权声明** | **CC0 1.0**（公共领域贡献）— 可自由复制、修改、用于测试与演示 |
| **禁止用途** | 请勿将本目录示意谱面当作真实敬拜诗歌的正式用谱发布 |
| **私有素材** | 本地放在 `samples/private/`（已 gitignore），**不要 push** |

## 当前文件

| 文件 | 说明 | 用途 | 来源 / 授权 |
|------|------|------|-------------|
| `001_poc_digits.png` | 清晰印刷风格合成谱：调号/拍号文字 + 两行数字简谱 + 拉丁歌词占位 | 默认冒烟 / UI 演示 | 仓库脚本绘制 · CC0 |
| `002_scan_like.png` | 在 001 内容基础上轻微模糊、噪声与旋转，模拟不完美扫描 | 预处理鲁棒性抽查 | 同上 · CC0 |
| `003_cn_lyrics.png` | 含中文说明与示意歌词行的合成谱（微软雅黑绘制） | 中文 OCR 路径演示 | 同上 · CC0 |

> 歌词与曲名均为 **示意占位**，不对应任何受版权保护的完整诗歌作品排版。

## 结构化乐谱示例（Schema v0.1）

| 文件 | 说明 |
|------|------|
| `scores/example-minimal.json` | 单声部 + 歌词的最小 EnPu Score（Issue #9） |
| `scores/example-minimal.musicxml` | 由上表 JSON 经 music21 导出（Issue #11，可 MuseScore 打开） |
| `scores/example-minimal.mid` | 同上导出的 MIDI |

```powershell
# 从 JSON 再导出（需已 pip install music21）
curl.exe -X POST "http://127.0.0.1:8765/v1/export?format=musicxml&download=true" `
  -H "Content-Type: application/json" `
  --data-binary "@samples/scores/example-minimal.json" `
  -o out.musicxml
```

规范文档：[`docs/jianpu-schema.md`](../docs/jianpu-schema.md)。
## 默认验收路径

```powershell
# 仓库根目录
.\scripts\start.ps1 -Engine mock    # 或默认 paddleocr
.\scripts\smoke-poc.ps1             # 默认使用 001_poc_digits.png

# 手动指定其它样例
.\scripts\smoke-poc.ps1 -Sample .\samples\002_scan_like.png
.\scripts\smoke-poc.ps1 -Sample .\samples\003_cn_lyrics.png
```

桌面 UI：导入上述任一 png →「开始识别」→ 查看 OCR / JSON。

## 命名建议

```text
samples/
  001_*.png    # 清晰印刷 / 合成
  002_*.png    # 扫描/噪声类
  003_*.png    # 中文/歌词类
  private/     # 本地私有（gitignore）
```

新增样例时请更新本表「来源 / 授权」列，并在 PR 中说明生成方式。

## 已知限制

- 合成字体与真实印刷简谱版式差异大，**OCR 精度不代表产品指标**
- Phase 0 只要求「可被 `/v1/recognize` 处理并返回稳定 JSON」
- 真实手机拍照、复杂反复记号等留给后续阶段样例集
