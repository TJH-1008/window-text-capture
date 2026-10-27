"""Native ttk scrollbars with small rounded thumbs and no arrow buttons."""

from PIL import Image, ImageDraw, ImageTk


def configure_scrollbars(root, style, scale):
    images = []
    for orientation in ('Vertical', 'Horizontal'):
        states = []
        for color in ('#C0C9C2', '#8DA493', '#486B53'):
            width, height = (9, 34) if orientation == 'Vertical' else (34, 9)
            size = (max(6, round(width*scale)), max(6, round(height*scale)))
            image = Image.new('RGBA', (size[0]*3, size[1]*3))
            ImageDraw.Draw(image).rounded_rectangle((3, 3, image.width-4, image.height-4),
                                                    radius=max(3, round(3*scale*3)), fill=color)
            photo = ImageTk.PhotoImage(image.resize(size, Image.Resampling.LANCZOS), master=root)
            states.append(photo)
            images.append(photo)
        element = f'Modern.{orientation}.Scrollbar.thumb'
        style.element_create(element, 'image', states[0], ('pressed', states[2]),
                             ('active', states[1]), border=max(2, round(3*scale)), sticky='nswe')
        style.layout(f'{orientation}.TScrollbar', [
            (f'{orientation}.Scrollbar.trough', {'sticky': 'ns' if orientation == 'Vertical' else 'ew',
             'children': [(element, {'sticky': 'nswe'})]})])
        style.configure(f'{orientation}.TScrollbar', background='#FAFAFA', troughcolor='#FAFAFA',
                        borderwidth=0, relief='flat', arrowsize=0, gripcount=0,
                        lightcolor='#FAFAFA', darkcolor='#FAFAFA', bordercolor='#FAFAFA')
    root._modern_scrollbar_images = images
