# EnPu 简谱 JSON Schema

> 状态：占位。v0.1 定稿见 Issue [#9](https://github.com/loootte/EnPu/issues/9)。

## 设计原则

1. **JSON 为内部真相源**；MusicXML / MIDI 为导出产物  
2. 先覆盖中文敬拜简谱常见子集：单声部旋律、调号、拍号、歌词  
3. 字段带 `schema_version`，便于演进  

## 草稿示例（非正式）

```json
{
  "schema_version": "0.1-draft",
  "title": "示例诗歌",
  "key": "C",
  "time_signature": "4/4",
  "tempo_bpm": 80,
  "parts": [
    {
      "name": "melody",
      "measures": [
        {
          "number": 1,
          "notes": [
            { "pitch": "1", "octave": 4, "duration": "quarter", "lyric": "主" }
          ]
        }
      ]
    }
  ]
}
```

音高采用数字简谱语义（`1`–`7` 及升降、高低点），与五线谱映射在导出层（music21）完成。

## 待定

- 反复记号、倚音、连音线  
- 多行歌词与和声部  
- 与 Pydantic 模型一一对应的 JSON Schema 文件  
