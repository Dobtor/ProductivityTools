# -*- coding: utf-8 -*-
"""把紅框與編號徽章畫進圖裡（manual 標註版）。

☠️ 為什麼不用 CSS 疊 div：slide.html_content 的 sanitizer 會吃掉 style／絕對定位，
  前台只剩一張沒標註的圖。所以在伺服端用 PIL 畫進「另一份」圖，原圖不動
  （行銷出口要乾淨版）。
"""
import io

from PIL import Image, ImageDraw, ImageFont

RED = (0xE0, 0x24, 0x24)
WHITE = (255, 255, 255)
#: shot_runner 的 viewport 寬度（CSS 像素）；座標要乘上 device_scale_factor
CSS_WIDTH = 1440


def _font(size):
    for name in ('DejaVuSans-Bold.ttf', 'Arial Bold.ttf', 'arialbd.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def draw_regions(png_bytes, regions, css_width=CSS_WIDTH):
    """回傳新的 PNG 位元組；regions: [{n,x,y,w,h}]（CSS 像素）。"""
    img = Image.open(io.BytesIO(png_bytes)).convert('RGB')
    if not regions:
        out = io.BytesIO()
        img.save(out, format='PNG', optimize=True)
        return out.getvalue()
    scale = max(1.0, round(img.width / float(css_width or img.width), 2))
    draw = ImageDraw.Draw(img)
    line = max(2, int(round(3 * scale)))
    radius = int(round(13 * scale))
    font = _font(int(round(15 * scale)))
    for idx, r in enumerate(regions, start=1):
        x, y = r.get('x', 0) * scale, r.get('y', 0) * scale
        w, h = r.get('w', 0) * scale, r.get('h', 0) * scale
        pad = 3 * scale
        draw.rectangle([x - pad, y - pad, x + w + pad, y + h + pad], outline=RED, width=line)
        # 徽章放在框的左上角外側；貼邊時往內收，避免被裁掉
        cx = min(max(x - pad, radius), img.width - radius)
        cy = min(max(y - pad, radius), img.height - radius)
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=RED)
        label = str(r.get('n') or idx)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2.0 - bbox[0], cy - th / 2.0 - bbox[1]), label,
                  fill=WHITE, font=font)
    out = io.BytesIO()
    img.save(out, format='PNG', optimize=True)
    return out.getvalue()
