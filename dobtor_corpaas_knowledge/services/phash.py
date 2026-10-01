# -*- coding: utf-8 -*-
"""感知雜湊（dHash）——判斷新舊截圖是否「看起來一樣」。

★ 不用檔案雜湊：Chromium 每次輸出的 PNG 位元組都可能不同（壓縮、metadata），
  用 sha 比對等於每次都換圖。dHash 對這種雜訊不敏感，對「按鈕位置變了」敏感。
"""
import io

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Odoo 一定有 PIL
    Image = None

HASH_SIZE = 16  # 16x16 → 256 bits；截圖細節多，8x8 太粗


def dhash(png_bytes, size=HASH_SIZE):
    """回傳十六進位字串。"""
    if Image is None:
        raise RuntimeError('PIL is required for dhash')
    img = Image.open(io.BytesIO(png_bytes)).convert('L').resize(
        (size + 1, size), Image.LANCZOS)
    px = list(img.getdata())
    bits = []
    for row in range(size):
        base = row * (size + 1)
        for col in range(size):
            bits.append(1 if px[base + col] > px[base + col + 1] else 0)
    value = 0
    for b in bits:
        value = (value << 1) | b
    return '%0*x' % (size * size // 4, value)


def distance(h1, h2):
    """兩個 dHash 的漢明距離；任一為空回最大值（視為不同）。"""
    if not h1 or not h2 or len(h1) != len(h2):
        return HASH_SIZE * HASH_SIZE
    return bin(int(h1, 16) ^ int(h2, 16)).count('1')
