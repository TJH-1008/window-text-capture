"""Neutralize toolbar icons in this isolated release, preserving alpha."""

from pathlib import Path
from PIL import Image


def main():
    assets = Path(__file__).with_name('assets')
    count = 0
    for path in assets.glob('*.png'):
        if path.stem.startswith(('workspace-', 'app', 'logo', 'illustration')):
            continue
        image = Image.open(path).convert('RGBA')
        pixels = []
        for r, g, b, alpha in image.getdata():
            if max(r, g, b) - min(r, g, b) > 15:
                r = g = b = 90
            pixels.append((r, g, b, alpha))
        image.putdata(pixels)
        image.save(path)
        count += 1
    print(f'Updated {count} local toolbar assets')


if __name__ == '__main__':
    main()
