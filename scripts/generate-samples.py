#!/usr/bin/env python3
"""Regenerate synthetic PoC samples under samples/ (CC0). Issue #7."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def write_001() -> Path:
    img = np.full((420, 900, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (20, 20), (880, 400), (30, 30, 30), 2)
    cv2.putText(
        img,
        "EnPu Sample 001 - Printed Clear (Synthetic)",
        (40, 55),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 0, 0),
        2,
    )
    cv2.putText(
        img,
        "Title: Amazing Grace (demo only, not real score layout)",
        (40, 95),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (40, 40, 40),
        1,
    )
    cv2.putText(
        img,
        "Key: C   Time: 3/4   Tempo: 80",
        (40, 130),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 0, 0),
        2,
    )
    cv2.putText(
        img,
        "1  .  2  .  3  |  5  -  -  |  6  5  3  |  2  -  -",
        (40, 200),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.95,
        (0, 0, 0),
        2,
    )
    cv2.putText(
        img,
        "1  .  2  .  3  |  5  -  -  |  3  2  1  |  1  -  -",
        (40, 260),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.95,
        (0, 0, 0),
        2,
    )
    cv2.putText(
        img,
        "lyrics (latin placeholder): A  -  maz - ing  grace",
        (40, 320),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (60, 60, 60),
        1,
    )
    cv2.putText(
        img,
        "Source: repo-generated for OCR PoC. CC0 / public domain content.",
        (40, 370),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (90, 90, 90),
        1,
    )
    path = SAMPLES / "001_poc_digits.png"
    cv2.imwrite(str(path), img)
    return path


def write_002(base: np.ndarray) -> Path:
    img2 = cv2.GaussianBlur(base.copy(), (3, 3), 0)
    noise = np.random.default_rng(42).integers(0, 18, img2.shape, dtype=np.uint8)
    img2 = cv2.add(img2, noise)
    h, w = img2.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 1.2, 1.0)
    img2 = cv2.warpAffine(img2, m, (w, h), borderValue=(255, 255, 255))
    cv2.putText(
        img2,
        "EnPu Sample 002 - Mild Skew/Noise (Synthetic scan-like)",
        (40, 55),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 0, 0),
        2,
    )
    path = SAMPLES / "002_scan_like.png"
    cv2.imwrite(str(path), img2)
    return path


def write_003() -> Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("skip 003: Pillow not installed")
        return None

    font_path = Path(r"C:\Windows\Fonts\msyh.ttc")
    if not font_path.is_file():
        # Linux/mac fallbacks — may not exist
        for cand in (
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/System/Library/Fonts/PingFang.ttc",
        ):
            if Path(cand).is_file():
                font_path = Path(cand)
                break
        else:
            print("skip 003: no CJK font found")
            return None

    font = ImageFont.truetype(str(font_path), 28)
    font_sm = ImageFont.truetype(str(font_path), 22)
    font_lg = ImageFont.truetype(str(font_path), 36)
    im = Image.new("RGB", (900, 380), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([15, 15, 885, 365], outline=(20, 20, 20), width=2)
    d.text((40, 30), "恩谱样例 003 · 中文歌词（合成）", fill=(0, 0, 0), font=font)
    d.text(
        (40, 80),
        "调：C    拍号：4/4    （自制示意，非真实诗歌版权素材）",
        fill=(40, 40, 40),
        font=font_sm,
    )
    d.text(
        (40, 150),
        "1  2  3  |  5  5  6  |  1  7  6  5  |  3  -  -  -",
        fill=(0, 0, 0),
        font=font_lg,
    )
    d.text((40, 220), "主 恩 典  够 我 用    心 中 满 有 平 安", fill=(0, 0, 0), font=font)
    d.text(
        (40, 300),
        "来源：仓库程序绘制 · 授权：CC0（可自由用于测试）",
        fill=(80, 80, 80),
        font=font_sm,
    )
    path = SAMPLES / "003_cn_lyrics.png"
    im.save(path)
    return path


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    p1 = write_001()
    print("wrote", p1, p1.stat().st_size)
    # reload for 002 base without label overwrite issues
    base = cv2.imread(str(p1))
    p2 = write_002(base)
    print("wrote", p2, p2.stat().st_size)
    p3 = write_003()
    if p3:
        print("wrote", p3, p3.stat().st_size)


if __name__ == "__main__":
    main()
