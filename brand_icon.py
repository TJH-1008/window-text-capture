"""程序化生成的品牌标志：深色圆角底 + 白色窗口 + 绿色捕捉点（方案 D）。

全部用几何绘制，不引用外部图片；每个尺寸独立超采样，保证 16px 任务栏也清晰。
小于等于 24px 时走简化版：去掉标题栏与窗口内的小圆点，只留窗口框、一行内容和绿点。

    python brand_icon.py     # 重新生成 assets/ 下的 app.png、app.ico、logo*.png
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
GRID = 34.0
TILE_TOP = (49, 49, 49)
TILE_BOTTOM = (28, 28, 28)
WHITE = '#FFFFFF'
LIME = '#8CF01F'


def _px(unit, value):
    return round(value * unit)


def _mask_round(unit, box, radius, size):
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([_px(unit, v) for v in box], radius=_px(unit, radius), fill=255)
    return mask


def _gradient_layer(unit, box, mask, top, bottom):
    size = mask.size[0]
    _, y0, _, y1 = (_px(unit, v) for v in box)
    height = max(1, y1 - y0)
    strip = Image.new('RGBA', (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        strip.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    layer.paste(strip.resize((size, height)), (0, y0))
    layer.putalpha(mask)
    return layer


def _draw_mark(image, draw, unit, simple, detail=True):
    """image 先铺底，draw 负责线框；分两步是因为圆角底的渐变要 alpha_composite。"""
    box, radius = (2, 2, 32, 32), 7.2
    mask = _mask_round(unit, box, radius, image.size[0])
    image.alpha_composite(_gradient_layer(unit, box, mask, TILE_TOP, TILE_BOTTOM))
    highlight = Image.new('RGBA', image.size, (0, 0, 0, 0))
    ImageDraw.Draw(highlight).rounded_rectangle(
        [_px(unit, box[0]), _px(unit, box[1]), _px(unit, box[2]), _px(unit, box[1] + (box[3] - box[1]) * 0.46)],
        radius=_px(unit, radius), fill=(255, 255, 255, 15))
    highlight.putalpha(ImageChops.multiply(highlight.getchannel('A'), mask))
    image.alpha_composite(highlight)

    draw = ImageDraw.Draw(image)
    window = (7.6, 9.0, 26.4, 25.0)
    draw.rounded_rectangle([_px(unit, v) for v in window], radius=_px(unit, 3.2),
                           outline=WHITE, width=max(1, _px(unit, 2.8 if simple else 2.4)))
    if not simple:
        # 标题栏让"这是窗口"立住；窗口里那个 1 单位小亮点只在 64px 以上才画，否则会糊成脏点。
        draw.line([(_px(unit, 7.6), _px(unit, 14.4)), (_px(unit, 26.4), _px(unit, 14.4))],
                  fill=WHITE, width=max(1, _px(unit, 2.2)))
        if detail:
            draw.ellipse([_px(unit, 11.4 - 1.15), _px(unit, 11.7 - 1.15),
                          _px(unit, 11.4 + 1.15), _px(unit, 11.7 + 1.15)], fill=LIME)
    draw.line([(_px(unit, 11.4), _px(unit, 19.0)), (_px(unit, 19.4), _px(unit, 19.0))],
              fill=WHITE, width=max(1, _px(unit, 3.0 if simple else 2.6)))
    radius_dot = 3.2 if simple else (3.0 if not detail else 2.9)
    draw.ellipse([_px(unit, 21.6 - radius_dot), _px(unit, 21.8 - radius_dot),
                  _px(unit, 21.6 + radius_dot), _px(unit, 21.8 + radius_dot)], fill=LIME)


def application_icon(size=1024):
    if size < 1:
        raise ValueError('Icon size must be positive')
    scale = 8 if size <= 64 else 4
    image = Image.new('RGBA', (size * scale, size * scale))
    _draw_mark(image, ImageDraw.Draw(image), size * scale / GRID,
               simple=size <= 24, detail=size > 64)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def export_icons(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    application_icon().save(output_dir / 'app.png')
    application_icon(256).save(
        output_dir / 'app.ico', sizes=[(n, n) for n in ICON_SIZES],
        append_images=[application_icon(n) for n in ICON_SIZES if n != 256])
    application_icon(44).save(output_dir / 'logo.png')
    for percent in range(75, 401, 25):
        application_icon(round(44 * percent / 100)).save(output_dir / f'logo-{percent}.png')


if __name__ == '__main__':
    export_icons(Path(__file__).with_name('assets'))
