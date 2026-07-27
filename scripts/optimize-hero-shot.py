#!/usr/bin/env python3
"""히어로 스크린샷을 웹에 올릴 크기로 줄인다.

capture-hero-shot.mjs 가 뽑은 2880px 원본은 1.8MB 라 히어로에 그대로 쓸 수 없다.
표시 폭이 약 760px 이므로 2x 인 1600px 이면 충분하다. 지도 타일이 섞인 사진성
이미지라 PNG 보다 WebP 가 훨씬 작다.

    python3 scripts/optimize-hero-shot.py
"""
import pathlib
from PIL import Image

SRC = pathlib.Path("public/landing/service-screen.png")
OUT = pathlib.Path("public/landing/service-screen.webp")
TARGET_WIDTH = 1600

im = Image.open(SRC).convert("RGB")
height = round(im.height * TARGET_WIDTH / im.width)
im = im.resize((TARGET_WIDTH, height), Image.LANCZOS)
im.save(OUT, "WEBP", quality=82, method=6)

print(f"{SRC} {SRC.stat().st_size / 1024:.0f}KB -> {OUT} {OUT.stat().st_size / 1024:.0f}KB  ({TARGET_WIDTH}x{height})")
