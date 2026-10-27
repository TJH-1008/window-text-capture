"""图标方案实验台：同一套几何在 34 单位网格上画，导出大图、小尺寸对照表和 ICO。

设计约束（与 docs/设计约定.md 一致）：
- 纯程序化绘制，不依赖外部素材；34 单位网格，留白 2 单位。
- 浅色底、深色底、16px 任务栏都必须能认出来：小于 32px 时走简化版，去掉细节线条。
- 只用一个强调色（绿），其余靠明度分层。

只用于设计比选，不参与运行。选定方案后把 draw_<方案> 写回 brand_icon.py。

    python icon_lab.py
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

GRID = 34.0
INK_TOP = (49, 49, 49)
INK_BOTTOM = (28, 28, 28)
POINT_TOP = (54, 54, 54)
GREEN = '#35A82F'
LIME = '#8CF01F'
WHITE = '#FFFFFF'
PAPER = '#FAFAFA'
HAIRLINE = '#E4E4E4'


# ---------------------------------------------------------------- 基础绘制
def _canvas(size, scale=4):
    image = Image.new('RGBA', (size * scale, size * scale))
    return image, ImageDraw.Draw(image), size * scale / GRID


def _px(unit, value):
    return round(value * unit)


def _line(draw, unit, points, color, width, joint='curve'):
    draw.line([(_px(unit, x), _px(unit, y)) for x, y in points], fill=color,
              width=max(1, _px(unit, width)), joint=joint)


def _dot(draw, unit, cx, cy, r, color):
    draw.ellipse([_px(unit, cx - r), _px(unit, cy - r), _px(unit, cx + r), _px(unit, cy + r)], fill=color)


def _mask_round(unit, box, radius, size_px):
    mask = Image.new('L', (size_px, size_px), 0)
    ImageDraw.Draw(mask).rounded_rectangle([_px(unit, v) for v in box], radius=_px(unit, radius), fill=255)
    return mask


def _gradient_layer(unit, box, mask, top, bottom):
    """在给定圆角遮罩内铺竖向渐变，返回可直接 alpha_composite 的图层。"""
    size = mask.size[0]
    x0, y0, x1, y1 = (_px(unit, v) for v in box)
    strip = Image.new('RGBA', (1, max(1, y1 - y0)))
    for y in range(strip.size[1]):
        t = min(max(y / max(1, strip.size[1] - 1), 0), 1)
        strip.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    layer.paste(strip.resize((size, max(1, y1 - y0))), (_px(unit, 0), y0))
    layer.putalpha(mask)
    return layer


def _tile(image, unit, box=(2, 2, 32, 32), radius=7.2, top=INK_TOP, bottom=INK_BOTTOM):
    """深色圆角底：竖向微弱渐变 + 顶部一道高光，避免大图像纯色方块。"""
    size = image.size[0]
    mask = _mask_round(unit, box, radius, size)
    image.alpha_composite(_gradient_layer(unit, box, mask, top, bottom))
    if radius > 3:
        highlight = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(highlight).rounded_rectangle(
            [_px(unit, box[0]), _px(unit, box[1]), _px(unit, box[2]), _px(unit, box[1] + (box[3] - box[1]) * 0.46)],
            radius=_px(unit, radius), fill=(255, 255, 255, 15))
        highlight.putalpha(ImageChops.multiply(highlight.getchannel('A'), mask))
        image.alpha_composite(highlight)


def _paper(image, unit, box, radius, fill='#FFFFFF'):
    size = image.size[0]
    mask = _mask_round(unit, box, radius, size)
    layer = Image.new('RGBA', (size, size), fill)
    image.paste(layer, (0, 0), mask)


# ---------------------------------------------------------------- 方案
def draw_a(image, draw, unit, simple=False):
    """A 角标 + 绿点：延续现有标志，折角更细、绿点下沉，留白更匀。"""
    _line(draw, unit, [(10.6, 12.6), (22.2, 12.6), (22.2, 24.2)], WHITE, 3.2 if simple else 3.0)
    _dot(draw, unit, 9.7, 22.5, 3.6 if simple else 3.4, LIME)


def draw_b(image, draw, unit, simple=False):
    """B 文本行：三条横线，末行绿色 —— 最直白地表达"文字"。"""
    for y, width in ((12.2, 16.4), (17.2, 20.6)):
        _line(draw, unit, [(8.2, y), (8.2 + width, y)], WHITE, 3.4 if simple else 3.0, joint=None)
    _line(draw, unit, [(8.2, 22.2), (19.0, 22.2)], LIME, 3.4 if simple else 3.0, joint=None)


def draw_c(image, draw, unit, simple=False):
    """C 取景框：四角括号 + 一行文本 + 绿色扫描线，白底更亮眼。"""
    arm, width = (6.4, 3.2) if simple else (5.6, 2.6)
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        x0 = 6.6 if sx > 0 else 27.4
        y0 = 6.6 if sy > 0 else 27.4
        _line(draw, unit, [(x0, y0 + sy * arm), (x0, y0), (x0 + sx * arm, y0)], INK_BOTTOM, width)
    _line(draw, unit, [(11.6, 14.8), (22.4, 14.8)], INK_BOTTOM, 3.0, joint=None)
    if not simple:
        _line(draw, unit, [(11.6, 19.4), (19.0, 19.4)], '#8A8A8A', 3.0, joint=None)
    _line(draw, unit, [(9.2, 23.6), (24.8, 23.6)], GREEN, 3.6 if simple else 3.0, joint=None)


def draw_d(image, draw, unit, simple=False):
    """D 窗口 + 捕捉点：窗口框 + 一行内容 + 右下绿点，强调"对窗口取数"。"""
    box = (7.6, 9.0, 26.4, 25.0)
    draw.rounded_rectangle([_px(unit, v) for v in box], radius=_px(unit, 3.2),
                           outline=WHITE, width=max(1, _px(unit, 2.8 if simple else 2.4)))
    if not simple:
        _line(draw, unit, [(7.6, 14.4), (26.4, 14.4)], WHITE, 2.2, joint=None)
        _dot(draw, unit, 11.4, 11.7, 1.15, LIME)
    _line(draw, unit, [(11.4, 19.0), (19.4, 19.0)], WHITE, 3.0 if simple else 2.6, joint=None)
    _dot(draw, unit, 21.6, 21.8, 3.2 if simple else 2.9, LIME)


def draw_e(image, draw, unit, simple=False):
    """E 叠层表格：两张错位纸片 + 绿色表头，偏"整理成表"。"""
    if not simple:
        _paper(image, unit, (10.4, 6.8, 25.4, 20.6), 3.0, '#585858')
    _paper(image, unit, (8.6, 11.0, 25.4, 27.2), 3.4, '#FFFFFF')
    draw = ImageDraw.Draw(image)
    _line(draw, unit, [(12.0, 16.0), (22.0, 16.0)], GREEN, 3.0, joint=None)
    _line(draw, unit, [(12.0, 20.4), (22.0, 20.4)], '#C4C4C4', 2.4, joint=None)
    if not simple:
        _line(draw, unit, [(12.0, 24.2), (18.4, 24.2)], '#C4C4C4', 2.4, joint=None)


def draw_f(image, draw, unit, simple=False):
    """F 圆形徽章：深墨圆 + 两行白字 + 绿点，任务栏里最稳。"""
    if not simple:
        # ImageDraw 不做 alpha 混合，带透明度的描边会直接抠掉底，这里用实色描边
        draw.ellipse([_px(unit, 3.6), _px(unit, 3.6), _px(unit, 30.4), _px(unit, 30.4)],
                     outline='#3C3C3C', width=max(1, _px(unit, 0.9)))
    _line(draw, unit, [(10.2, 13.6), (23.8, 13.6)], WHITE, 3.4 if simple else 3.0, joint=None)
    _line(draw, unit, [(10.2, 19.2), (23.8, 19.2)], WHITE, 3.4 if simple else 3.0, joint=None)
    _line(draw, unit, [(10.2, 24.8), (17.4, 24.8)], LIME, 3.4 if simple else 3.0, joint=None)


DESIGNS = (
    ('A', '角标 + 绿点', draw_a, 'flake'),
    ('B', '文本行', draw_b, 'tile'),
    ('C', '取景框 + 扫描线', draw_c, 'paper'),
    ('D', '窗口 + 捕捉点', draw_d, 'tile'),
    ('E', '叠层表格', draw_e, 'tile'),
    ('F', '圆形徽章', draw_f, 'circle'),
)


def render(design, size, scale=6):
    key, title, func, ground = design
    image, draw, unit = _canvas(size, scale)
    simple = size <= 24
    if ground == 'tile':
        _tile(image, unit, top=INK_TOP, bottom=INK_BOTTOM)
        draw = ImageDraw.Draw(image)
    elif ground == 'paper':
        _paper(image, unit, (2, 2, 32, 32), 7.2, '#F5F6F5')
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle([_px(unit, 2), _px(unit, 2), _px(unit, 32), _px(unit, 32)],
                               radius=_px(unit, 7.2), outline='#DCDDDC', width=max(1, _px(unit, 0.7)))
    elif ground == 'circle':
        mask = Image.new('L', image.size, 0)
        ImageDraw.Draw(mask).ellipse([_px(unit, v) for v in (2, 2, 32, 32)], fill=255)
        image.alpha_composite(_gradient_layer(unit, (2, 2, 32, 32), mask, (44, 44, 44), (24, 24, 24)))
        draw = ImageDraw.Draw(image)
    elif ground == 'flake':
        _tile(image, unit, top=POINT_TOP, bottom=(30, 30, 30))
        draw = ImageDraw.Draw(image)
    func(image, draw, unit, simple=simple)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def contact_sheet(output):
    big = 168
    row_h = big + 52
    width = 1160
    sheet = Image.new('RGBA', (width, row_h * len(DESIGNS) + 96), PAPER)
    draw = ImageDraw.Draw(sheet)
    try:
        title_font = ImageFont.truetype('msyhbd.ttc', 21)
        font = ImageFont.truetype('msyh.ttc', 17)
        tiny = ImageFont.truetype('msyh.ttc', 13)
    except OSError:
        title_font = font = tiny = ImageFont.load_default()
    draw.text((36, 24), '图标方案比选', font=title_font, fill='#262626')
    draw.text((36, 56), '左侧看造型；右侧是 64 / 48 / 32 / 24 / 16px 的实际观感，深色条模拟深色任务栏',
              font=tiny, fill='#6A6A6A')
    sizes = (64, 48, 32, 24, 16)
    for index, design in enumerate(DESIGNS):
        key, title, func, ground = design
        top = 92 + index * row_h
        draw.rectangle([18, top - 10, width - 18, top + row_h - 18], fill='#FFFFFF' if index % 2 == 0 else PAPER)
        draw.text((36, top + 2), key, font=title_font, fill='#262626')
        draw.text((68, top + 6), title, font=font, fill='#3A3A3A')
        draw.text((68, top + 30), {'tile': '深色圆角底', 'paper': '浅色圆角底', 'circle': '深色圆形底',
                                   'flake': '深色圆角底（弱化）'}[ground], font=tiny, fill='#9A9A9A')
        sheet.alpha_composite(render(design, big, scale=4), (32, top + 50))
        x = 240
        for size in sizes:
            icon = render(design, size, scale=8)
            sheet.alpha_composite(icon, (x, top + 62))
            draw.text((x + size // 2 - len(str(size)) * 3, top + 40), str(size), font=tiny, fill='#9A9A9A')
            x += size + 26
        strip_top = top + 30
        draw.rounded_rectangle([760, strip_top, 1000, strip_top + 68], radius=10, fill='#1E1E1E')
        x = 776
        for size in (48, 32, 24, 16):
            icon = render(design, size, scale=8)
            sheet.alpha_composite(icon, (x, strip_top + 10))
            x += size + 20
        draw.text((1016, strip_top + 24), '深色任务栏', font=tiny, fill='#9A9A9A')
        draw.line([(18, top + row_h - 20), (width - 18, top + row_h - 20)], fill='#EDEDED')
    sheet.convert('RGB').save(output)
    return output


def export(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, title, func, ground in DESIGNS:
        folder = output_dir / f'方案{key}'
        folder.mkdir(exist_ok=True)
        design = (key, title, func, ground)
        render(design, 1024, scale=4).save(folder / 'preview-1024.png')
        render(design, 256).save(folder / 'app.ico',
                                 sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)],
                                 append_images=[render(design, n, scale=8)
                                                for n in (16, 20, 24, 32, 40, 48, 64, 96, 128)])
        for size in (16, 24, 32, 48, 256):
            render(design, size, scale=8).save(folder / f'icon-{size}.png')
    return contact_sheet(output_dir / '方案对照表.png')


if __name__ == '__main__':
    print(export(Path(__file__).with_name('assets') / 'icons-lab'))
