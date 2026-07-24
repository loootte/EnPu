#!/usr/bin/env python3
"""Generate synthetic eval set (15 sheets + ground-truth Score JSON) for issue #29.

Output:
  samples/eval/images/E01_*.png … E15_*.png
  samples/eval/gt/E01_*.json … E15_*.json
  samples/eval/manifest.json

All content is program-drawn (CC0). Not real worship song engravings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "samples" / "eval"
IMG_DIR = EVAL / "images"
GT_DIR = EVAL / "gt"


@dataclass
class NoteSpec:
    pitch: str | None  # "1"-"7" or None for rest
    duration: str = "quarter"
    dots: int = 0
    is_rest: bool = False
    lyric: str | None = None
    octave: int = 0

    def to_token(self) -> str:
        if self.is_rest or self.pitch is None:
            return "0"
        return self.pitch

    def to_event(self) -> dict[str, Any]:
        if self.is_rest or self.pitch is None:
            return {
                "pitch": None,
                "octave": 0,
                "duration": self.duration,
                "dots": self.dots,
                "is_rest": True,
                "lyric": None,
            }
        return {
            "pitch": self.pitch,
            "octave": self.octave,
            "duration": self.duration,
            "dots": self.dots,
            "is_rest": False,
            "lyric": self.lyric,
        }


@dataclass
class EvalCase:
    id: str
    title: str
    key: str
    time_signature: str
    tempo_bpm: float
    subset: str  # print_clear | scan_like | cn_lyrics
    measures: list[list[NoteSpec]]
    lyric_line: str = ""
    notes: str = ""
    seed: int = 0

    def pitch_sequence(self) -> list[str]:
        out: list[str] = []
        for m in self.measures:
            for n in m:
                if not n.is_rest and n.pitch:
                    out.append(n.pitch)
        return out

    def to_score(self) -> dict[str, Any]:
        parts_measures = []
        for i, notes in enumerate(self.measures, start=1):
            parts_measures.append(
                {
                    "number": i,
                    "notes": [n.to_event() for n in notes],
                }
            )
        return {
            "schema_version": "0.1",
            "title": self.title,
            "key": self.key,
            "time_signature": self.time_signature,
            "tempo_bpm": self.tempo_bpm,
            "parts": [
                {
                    "id": "P1",
                    "name": "melody",
                    "measures": parts_measures,
                }
            ],
            "meta": {
                "created_by": "enpu-generate-eval-samples",
                "comments": "Synthetic eval ground-truth (CC0). Not a published song.",
                "source_image": f"images/{self.id}.png",
                "engine": None,
                "extra": {
                    "eval": {
                        "id": self.id,
                        "subset": self.subset,
                        "license": "CC0-1.0",
                        "pitch_sequence": self.pitch_sequence(),
                        "measure_count": len(self.measures),
                        "synthetic": True,
                    }
                },
            },
            "extra": {
                "eval": {
                    "id": self.id,
                    "subset": self.subset,
                    "license": "CC0-1.0",
                    "pitch_sequence": self.pitch_sequence(),
                    "measure_count": len(self.measures),
                    "synthetic": True,
                }
            },
        }

    def measure_tokens(self) -> list[list[str]]:
        return [[n.to_token() for n in m] for m in self.measures]


def q(pitch: str, lyric: str | None = None) -> NoteSpec:
    return NoteSpec(pitch=pitch, duration="quarter", lyric=lyric)


def h(pitch: str, lyric: str | None = None) -> NoteSpec:
    return NoteSpec(pitch=pitch, duration="half", lyric=lyric)


def hd(pitch: str, lyric: str | None = None) -> NoteSpec:
    return NoteSpec(pitch=pitch, duration="half", dots=1, lyric=lyric)


def w(pitch: str, lyric: str | None = None) -> NoteSpec:
    return NoteSpec(pitch=pitch, duration="whole", lyric=lyric)


def rest_q() -> NoteSpec:
    return NoteSpec(pitch=None, duration="quarter", is_rest=True)


def rest_h() -> NoteSpec:
    return NoteSpec(pitch=None, duration="half", is_rest=True)


def build_cases() -> list[EvalCase]:
    """15 synthetic cases: 10 print_clear, 3 scan_like, 2 cn_lyrics."""
    cases: list[EvalCase] = []

    # E01 — C 4/4 classic demo
    cases.append(
        EvalCase(
            id="E01_print_c_4_4_grace_demo",
            title="示意·奇异恩典骨架",
            key="C",
            time_signature="4/4",
            tempo_bpm=80,
            subset="print_clear",
            lyric_line="主 爱 永 不 变  恩 典 够 我 用",
            measures=[
                [q("1", "主"), q("2", "爱"), q("3", "永"), q("5", "不")],
                [h("5", "变"), q("6", "恩"), q("5", "典")],
                [q("3", "够"), q("2", "我"), h("1", "用")],
                [w("1")],
            ],
            notes="Simple C major 4 bars",
            seed=1,
        )
    )

    # E02 — G 4/4
    cases.append(
        EvalCase(
            id="E02_print_g_4_4_ascending",
            title="示意·上行音阶片段",
            key="G",
            time_signature="4/4",
            tempo_bpm=96,
            subset="print_clear",
            lyric_line="一 步 一 步 跟 着 主 走",
            measures=[
                [q("1"), q("2"), q("3"), q("4")],
                [q("5"), q("6"), q("7"), q("1")],
                [h("5"), h("3")],
                [w("1")],
            ],
            seed=2,
        )
    )

    # E03 — F 3/4 waltz
    cases.append(
        EvalCase(
            id="E03_print_f_3_4_waltz",
            title="示意·三拍子片段",
            key="F",
            time_signature="3/4",
            tempo_bpm=90,
            subset="print_clear",
            lyric_line="心 中 满 有 平 安",
            measures=[
                [q("1"), q("3"), q("5")],
                [hd("5")],
                [q("6"), q("5"), q("3")],
                [hd("1")],
            ],
            seed=3,
        )
    )

    # E04 — D 4/4 with holds
    cases.append(
        EvalCase(
            id="E04_print_d_4_4_holds",
            title="示意·延音与半音符",
            key="D",
            time_signature="4/4",
            tempo_bpm=72,
            subset="print_clear",
            lyric_line="靠 主 得 力 量",
            measures=[
                [h("5"), h("3")],
                [q("2"), q("3"), h("5")],
                [hd("6"), q("5")],
                [w("1")],
            ],
            seed=4,
        )
    )

    # E05 — C 2/4
    cases.append(
        EvalCase(
            id="E05_print_c_2_4_march",
            title="示意·二拍子进行",
            key="C",
            time_signature="2/4",
            tempo_bpm=110,
            subset="print_clear",
            lyric_line="前 进 前 进",
            measures=[
                [q("1"), q("5")],
                [q("3"), q("5")],
                [q("6"), q("5")],
                [h("1")],
                [q("2"), q("3")],
                [h("1")],
            ],
            seed=5,
        )
    )

    # E06 — Bb 4/4
    cases.append(
        EvalCase(
            id="E06_print_bb_4_4_pentatonic",
            title="示意·降B 五声骨架",
            key="Bb",
            time_signature="4/4",
            tempo_bpm=84,
            subset="print_clear",
            lyric_line="敬 拜 荣 耀 君 王",
            measures=[
                [q("1"), q("2"), q("3"), q("5")],
                [q("6"), q("5"), q("3"), q("2")],
                [h("1"), h("5")],
                [w("1")],
            ],
            seed=6,
        )
    )

    # E07 — C with rests
    cases.append(
        EvalCase(
            id="E07_print_c_4_4_rests",
            title="示意·休止符",
            key="C",
            time_signature="4/4",
            tempo_bpm=88,
            subset="print_clear",
            lyric_line="静 默 片 刻",
            measures=[
                [q("1"), rest_q(), q("3"), rest_q()],
                [h("5"), rest_h()],
                [q("6"), q("5"), rest_q(), q("3")],
                [w("1")],
            ],
            seed=7,
        )
    )

    # E08 — A 3/4
    cases.append(
        EvalCase(
            id="E08_print_a_3_4_gentle",
            title="示意·A 调轻柔",
            key="A",
            time_signature="3/4",
            tempo_bpm=76,
            subset="print_clear",
            lyric_line="主 与 我 同 在",
            measures=[
                [q("3"), q("2"), q("1")],
                [hd("5")],
                [q("6"), q("5"), q("3")],
                [hd("1")],
            ],
            seed=8,
        )
    )

    # E09 — C 4/4 longer 6 bars
    cases.append(
        EvalCase(
            id="E09_print_c_4_4_six_bars",
            title="示意·六小节旋律",
            key="C",
            time_signature="4/4",
            tempo_bpm=92,
            subset="print_clear",
            lyric_line="从 今 直 到 永 远 称 颂",
            measures=[
                [q("1"), q("1"), q("2"), q("3")],
                [q("5"), q("5"), h("3")],
                [q("6"), q("5"), q("3"), q("2")],
                [h("1"), h("5")],
                [q("3"), q("2"), q("1"), q("2")],
                [w("1")],
            ],
            seed=9,
        )
    )

    # E10 — Eb 4/4
    cases.append(
        EvalCase(
            id="E10_print_eb_4_4_cadence",
            title="示意·降E 收束",
            key="Eb",
            time_signature="4/4",
            tempo_bpm=70,
            subset="print_clear",
            lyric_line="阿 们 阿 们",
            measures=[
                [q("5"), q("3"), q("2"), q("1")],
                [h("2"), h("5")],
                [q("1"), q("3"), h("5")],
                [w("1")],
            ],
            seed=10,
        )
    )

    # E11–E13 scan_like (content cloned from E01–E03 with degraded rendering)
    base_print = list(cases)  # E01–E10
    cases.append(
        EvalCase(
            id="E11_scan_c_4_4_grace_demo",
            title="示意·奇异恩典骨架（扫描）",
            key="C",
            time_signature="4/4",
            tempo_bpm=80,
            subset="scan_like",
            measures=base_print[0].measures,
            lyric_line=base_print[0].lyric_line,
            seed=111,
        )
    )
    cases.append(
        EvalCase(
            id="E12_scan_g_4_4_ascending",
            title="示意·上行音阶（扫描）",
            key="G",
            time_signature="4/4",
            tempo_bpm=96,
            subset="scan_like",
            measures=base_print[1].measures,
            lyric_line=base_print[1].lyric_line,
            seed=112,
        )
    )
    cases.append(
        EvalCase(
            id="E13_scan_f_3_4_waltz",
            title="示意·三拍子（扫描）",
            key="F",
            time_signature="3/4",
            tempo_bpm=90,
            subset="scan_like",
            measures=base_print[2].measures,
            lyric_line=base_print[2].lyric_line,
            seed=113,
        )
    )

    # E14–E15 cn_lyrics style (more Chinese labels)
    cases.append(
        EvalCase(
            id="E14_cn_c_4_4_worship_line",
            title="示意·中文歌词行",
            key="C",
            time_signature="4/4",
            tempo_bpm=78,
            subset="cn_lyrics",
            lyric_line="主 恩 典 够 我 用  心 中 满 有 平 安",
            measures=[
                [q("1", "主"), q("2", "恩"), q("3", "典"), q("5", "够")],
                [h("5", "我"), q("6", "用"), q("5", "心")],
                [q("1", "中"), q("7", "满"), q("6", "有"), q("5", "平")],
                [w("3", "安")],
            ],
            seed=14,
        )
    )
    cases.append(
        EvalCase(
            id="E15_cn_g_4_4_praise",
            title="示意·赞美短句",
            key="G",
            time_signature="4/4",
            tempo_bpm=100,
            subset="cn_lyrics",
            lyric_line="荣 耀 归 主 名",
            measures=[
                [q("5", "荣"), q("5", "耀"), q("6", "归"), q("5", "主")],
                [h("3", "名"), h("2")],
                [q("1"), q("2"), q("3"), q("5")],
                [w("1")],
            ],
            seed=15,
        )
    )

    assert len(cases) == 15, len(cases)
    return cases


def _find_cjk_font() -> Path | None:
    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def render_case(case: EvalCase, out_path: Path) -> None:
    """Draw a jianpu-like sheet; graphic barlines for OCR robustness."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except ImportError as exc:
        raise SystemExit("Pillow required: pip install Pillow") from exc

    import numpy as np

    font_path = _find_cjk_font()
    if font_path:
        font_title = ImageFont.truetype(str(font_path), 26)
        font_meta = ImageFont.truetype(str(font_path), 20)
        font_num = ImageFont.truetype(str(font_path), 40)
        font_sm = ImageFont.truetype(str(font_path), 18)
    else:
        font_title = ImageFont.load_default()
        font_meta = font_title
        font_num = font_title
        font_sm = font_title

    w, h = 1100, 420
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([12, 12, w - 12, h - 12], outline=(20, 20, 20), width=2)

    d.text((36, 28), f"EnPu Eval {case.id}", fill=(0, 0, 0), font=font_title)
    d.text(
        (36, 68),
        f"标题：{case.title}    调：{case.key}    拍号：{case.time_signature}    速度：{int(case.tempo_bpm)}",
        fill=(30, 30, 30),
        font=font_meta,
    )
    d.text(
        (36, 100),
        f"子集：{case.subset} · 合成示意谱（CC0）· 非真实出版乐谱",
        fill=(80, 80, 80),
        font=font_sm,
    )

    # Pitch line with graphic bars
    groups = case.measure_tokens()
    y_top, y_bot = 150, 220
    x = 48
    gap = 44
    bar_gap = 26
    for gi, group in enumerate(groups):
        for tok in group:
            # map rest/dash display
            disp = tok if tok != "0" else "0"
            d.text((x, 160), disp, fill=(0, 0, 0), font=font_num)
            x += gap
        if gi < len(groups) - 1:
            bx = x + bar_gap // 2 - 10
            d.line([(bx, y_top), (bx, y_bot)], fill=(0, 0, 0), width=4)
            x += bar_gap

    if case.lyric_line:
        d.text((36, 250), case.lyric_line, fill=(0, 0, 0), font=font_meta)

    d.text(
        (36, 310),
        "音高序列 GT: " + " ".join(case.pitch_sequence()),
        fill=(60, 60, 60),
        font=font_sm,
    )
    d.text(
        (36, 350),
        "来源：scripts/generate-eval-samples.py · 授权 CC0 · Issue #29",
        fill=(100, 100, 100),
        font=font_sm,
    )

    if case.subset == "scan_like":
        rng = np.random.default_rng(case.seed)
        arr = np.array(im)
        # mild noise + blur + slight rotation via PIL
        noise = rng.integers(0, 22, arr.shape, dtype=np.uint8)
        arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        im = Image.fromarray(arr)
        im = im.filter(ImageFilter.GaussianBlur(radius=0.8))
        im = im.rotate(rng.uniform(-1.5, 1.5), fillcolor=(255, 255, 255), expand=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)


def write_manifest(cases: list[EvalCase]) -> dict[str, Any]:
    entries = []
    for c in cases:
        entries.append(
            {
                "id": c.id,
                "subset": c.subset,
                "image": f"images/{c.id}.png",
                "gt": f"gt/{c.id}.json",
                "key": c.key,
                "time_signature": c.time_signature,
                "measure_count": len(c.measures),
                "pitch_sequence": c.pitch_sequence(),
                "synthetic": True,
                "license": "CC0-1.0",
                "status": "ready",
            }
        )
    # Placeholders for user-provided 5
    for i in range(1, 6):
        mid = f"M{i:02d}_manual"
        entries.append(
            {
                "id": mid,
                "subset": "manual_real",
                "image": f"manual/{mid}.png",
                "gt": f"manual/{mid}.gt.json",
                "key": None,
                "time_signature": None,
                "measure_count": None,
                "pitch_sequence": None,
                "synthetic": False,
                "license": "user-provided-see-manual-README",
                "status": "pending_user",
            }
        )
    return {
        "schema": "enpu-eval-manifest-v0.1",
        "issue": 29,
        "description": "Recognition accuracy eval set. Synthetic E01–E15 generated; M01–M05 reserved for user real scores.",
        "counts": {
            "synthetic_ready": 15,
            "manual_slots": 5,
            "target_total": 20,
        },
        "subsets": {
            "print_clear": 10,
            "scan_like": 3,
            "cn_lyrics": 2,
            "manual_real": 5,
        },
        "entries": entries,
    }


def main() -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    GT_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL / "manual").mkdir(parents=True, exist_ok=True)

    cases = build_cases()
    for case in cases:
        img_path = IMG_DIR / f"{case.id}.png"
        gt_path = GT_DIR / f"{case.id}.json"
        render_case(case, img_path)
        score = case.to_score()
        gt_path.write_text(
            json.dumps(score, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("wrote", img_path.name, gt_path.name)

    manifest = write_manifest(cases)
    man_path = EVAL / "manifest.json"
    man_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("wrote", man_path)
    print("done:", len(cases), "synthetic cases")


if __name__ == "__main__":
    main()
