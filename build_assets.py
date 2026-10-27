"""Generate local vector-inspired icons at build time (Pillow only)."""

from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFilter
from brand_icon import application_icon, export_icons

ASSETS = Path(__file__).with_name('assets')
PURPLE = '#C33F7D'


def action_icon(name, color, size=20):
    scale = 4*size/20
    image = Image.new('RGBA', (round(20*scale), round(20*scale)))
    d = ImageDraw.Draw(image)
    def line(points):
        d.line(tuple(int(v*scale) for v in points), fill=color, width=round(2*scale), joint='curve')
    def rect(coords, radius=2):
        d.rounded_rectangle(tuple(int(v*scale) for v in coords), radius=round(radius*scale), outline=color, width=round(2*scale))
    if name == 'window':
        rect((2, 3, 18, 17)); line((3, 7, 17, 7)); line((6, 11, 14, 11)); line((6, 14, 11, 14))
    elif name == 'list':
        for y in (5, 10, 15):
            line((3, y, 4, y)); line((8, y, 17, y))
    elif name == 'table':
        rect((2, 3, 18, 17)); line((3, 8, 17, 8)); line((8, 4, 8, 16)); line((3, 12, 17, 12))
    elif name == 'folder':
        line((2, 16, 2, 4, 8, 4, 10, 7, 18, 7, 18, 16, 2, 16))
    elif name == 'archive':
        rect((3, 3, 17, 17)); line((10, 4, 10, 12)); line((7, 10, 10, 13, 13, 10))
    elif name == 'refresh':
        d.arc((3*scale, 3*scale, 17*scale, 17*scale), 40, 315, fill=color, width=round(2*scale))
        line((17, 2, 17, 7, 12, 7))
    elif name == 'import':
        line((3, 12, 3, 17, 17, 17, 17, 12)); line((10, 2, 10, 12)); line((6, 8, 10, 12, 14, 8))
    elif name == 'play':
        d.polygon(tuple((x*scale, y*scale) for x, y in ((6, 3), (17, 10), (6, 17))), fill=color)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def gradient_source(name):
    width, height = 2600, 720
    palettes = {
        'queue': ('#FFF5F9', '#F7C3D9', '#DF5D98', '#922D68'),
        'capture': ('#FFF7F8', '#F8C8D0', '#EE829A', '#AA3D70'),
        'excel': ('#FFF6F8', '#EFC1DB', '#D972A5', '#813B77'),
    }
    stops = [tuple(bytes.fromhex(color.lstrip('#'))) for color in palettes[name]]
    gradient = Image.new('RGBA', (width, height))
    pixels = gradient.load()
    for x in range(width):
        position = x / (width - 1) * (len(stops) - 1)
        index = min(len(stops) - 2, int(position))
        amount = position - index
        color = tuple(round(a + (b-a)*amount) for a, b in zip(stops[index], stops[index+1]))
        for y in range(height):
            glow = max(0, 1 - math.sqrt(((x/width-.55)/.7)**2 + ((y/height-.2)/.9)**2)) * .18
            pixels[x, y] = tuple(round(channel + (255-channel)*glow) for channel in color) + (255,)
    curves = Image.new('RGBA', gradient.size)
    draw = ImageDraw.Draw(curves)
    draw.ellipse((width*.57, -height*.95, width*1.07, height*1.25), fill=(255, 241, 248, 42))
    draw.ellipse((width*.72, -height*.72, width*1.12, height*1.18), outline=(255, 255, 255, 82), width=5)
    draw.arc((width*.47, -height*.9, width*1.03, height*1.45), 40, 250, fill=(255, 255, 255, 75), width=5)
    base = Image.alpha_composite(gradient, curves.filter(ImageFilter.GaussianBlur(1.5)))
    veil = Image.new('RGBA', base.size)
    draw = ImageDraw.Draw(veil)
    for x in range(width):
        alpha = round(244 * (1-min(1, x/(width*.78)))**.7)
        draw.line((x, 0, x, height), fill=(255, 249, 252, alpha))
    return Image.alpha_composite(base, veil)


def collection_art(name, size=(520, 440)):
    width, height = size
    scale = width / 520
    palettes = {'queue': ('#C23D7B', '#A94C7D'),
                'capture': ('#D65D75', '#B44D6C'),
                'excel': ('#9C4C86', '#824078')}
    accent, stream = palettes[name]
    art = Image.new('RGBA', size)
    d = ImageDraw.Draw(art)
    def rect(box, fill, radius=18, outline=None, stroke=1):
        d.rounded_rectangle(tuple(round(v*scale) for v in box), radius=round(radius*scale),
                            fill=fill, outline=outline, width=max(1, round(stroke*scale)))
    def line(points, fill, stroke=2):
        d.line(tuple(round(v*scale) for v in points), fill=fill, width=max(1, round(stroke*scale)), joint='curve')
    rect((120, 82, 424, 314), (143, 47, 112, 42), 24)
    rect((88, 106, 393, 341), (255, 255, 255, 170), 24)
    rect((51, 126, 359, 362), (255, 255, 255, 245), 23, (255, 255, 255, 225), 2)
    rect((51, 126, 359, 168), (255, 248, 252, 255), 23)
    d.rectangle((round(51*scale), round(151*scale), round(359*scale), round(169*scale)), fill=(255, 248, 252, 255))
    for x, color in ((75, '#EE82A9'), (92, '#F2B85F'), (109, '#79CBB2')):
        d.ellipse((round(x*scale), round(142*scale), round((x+8)*scale), round(150*scale)), fill=color)
    line((78, 193, 267, 193), accent, 5)
    line((78, 215, 305, 215), '#E5D7E0', 4)
    line((78, 233, 246, 233), '#E5D7E0', 4)
    for x, color in ((80, '#F4B2CC'), (112, '#E8C9DD'), (144, '#F4D4BE')):
        rect((x, 258, x+22, 280), color, 6)
        line((x+30, 265, x+78, 265), '#C8BAC5', 3)
        line((x+30, 276, x+64, 276), '#E2D9E0', 3)
    rect((258, 292, 337, 320), accent, 10)
    line((275, 306, 286, 315, 320, 298), 'white', 4)
    rect((373, 190, 477, 278), (255, 255, 255, 205), 16, (255, 255, 255, 230), 2)
    if name == 'queue':
        for y, length in ((211, 66), (229, 78), (247, 49)):
            line((390, y, 390+length, y), stream, 4)
        line((455, 287, 473, 306, 477, 278), '#7D315D', 5)
    elif name == 'capture':
        for y, length in ((210, 70), (229, 53), (248, 73)):
            rect((389, y, 396, y+7), accent, 3)
            line((405, y+3, 405+length, y+3), stream, 3)
        d.ellipse((round(449*scale), round(273*scale), round(480*scale), round(304*scale)),
                  fill=(255, 255, 255, 220), outline=accent, width=max(1, round(3*scale)))
        line((466, 299, 482, 316), '#7D315D', 5)
    else:
        for y in (208, 224, 240):
            line((388, y, 462, y), '#D9C4D4', 2)
        for x in (410, 432, 454):
            line((x, 201, x, 256), '#D9C4D4', 2)
        for x, bar_height in ((393, 13), (415, 25), (437, 18), (459, 34)):
            rect((x, 270-bar_height, x+10, 270), accent, 3)
    return art


def workspace_cover(name):
    width, height = 2600, 720
    base = gradient_source(name)
    stack = collection_art(name).resize((520, 440), Image.Resampling.LANCZOS)
    base.alpha_composite(stack, (width-660, (height-stack.height)//2))
    mask = Image.new('L', base.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width-1, height-1), radius=65, fill=255)
    base.putalpha(mask)
    target = ASSETS / f'workspace-cover-{name}.png'
    temporary = target.with_suffix('.pending.png')
    base.save(temporary, optimize=True)
    temporary.replace(target)


def main():
    ASSETS.mkdir(exist_ok=True)
    export_icons(ASSETS)
    for name in ('window', 'list', 'table', 'folder', 'archive', 'refresh', 'import'):
        action_icon(name, '#626262').save(ASSETS / (name + '.png'))
    action_icon('play', 'white', size=18).save(ASSETS / 'play-white.png')
    for name in ('queue', 'capture', 'excel'):
        workspace_cover(name)
    for percent in range(75, 401, 25):
        factor = percent/100
        application_icon(round(44*factor)).save(ASSETS / f'logo-{percent}.png')
        for name in ('window', 'list', 'table', 'folder', 'archive', 'refresh', 'import'):
            action_icon(name, '#626262', size=round(20*factor)).save(ASSETS / f'{name}-{percent}.png')
        action_icon('play', 'white', size=round(18*factor)).save(ASSETS / f'play-white-{percent}.png')
    print(ASSETS)


if __name__ == '__main__':
    main()
