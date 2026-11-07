#!/usr/bin/env python3
"""Creates a map icon (79x78 PNG) from an image.

Layer order, bottom to top:
    motif -> InnerCircleMask (white ring) -> WhiteHalo, clipped to WhiteCircle

Examples:
    python make_map_icon.py Image.jpg                 -> Image_icon.png
    python make_map_icon.py Image.jpg Clock.png       custom output name
    python make_map_icon.py Egg.jpg --fit contain     show the whole motif, rest stays white
    python make_map_icon.py Image.jpg --size 100      enlarge the motif
    python make_map_icon.py Image.jpg --offset -1 0   shift the motif

Requires Pillow (pip install pillow).
"""
import argparse
import base64
import io
import math
import sys
from pathlib import Path

from PIL import Image, ImageOps

CANVAS = (79, 78)
CENTER = (39, 39)        # center of the motif circle
DEFAULT_SIZE = 80

WHITE_CIRCLE = """
iVBORw0KGgoAAAANSUhEUgAAAE8AAABOCAAAAABEAxT/AAABbklEQVR42sWZ63HCMBCEP4kOkhakYkwvSjGiF7uG
0MKpBlq4/IjJTB6Aba3JFvDN3sOMbgk8UMoppwxgzZo1OpTK6D81lrQRVv2GrKynDeb3ZIOStpK4gObubgsbWX2p
lvRx8BV6bLH4Oj2wOPpa1XsrZ75eoxbnblrcTYdbcTeA1ber9C/Kd/36+JL3Kcma9+eQi/dqrjjMq0K3PkkHAN5f
+nmX8xdVYW9GHVT24HW6Qh1UBiNQNTjKzBTZo2WIkEQ4UoIIbyoeAwQwmcGWCbr2AYHIoMORxLxhB14S8jJBOQ4I
UWkPiFmKSxGxP229We6vSXEm92dSXJPvs9YeEeVAjMgk5E1ynv73XtjABhFhwVXMm3Z5b3DSlbvLe0004ZPs+Ph1
gpgAV3a8Fy6X7lfHse15b8nuwcP1uumr+HiW3tP1Cfe+PI/YOhN7Vp4jz5v0edjKvM4HaZ5Y/yXvlOex+rxYn2dv
zduD+P+AD9f8FP9kxCK6AAAAAElFTkSuQmCC
"""
WHITE_HALO = """
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
"""
INNER_CIRCLE_MASK = """
iVBORw0KGgoAAAANSUhEUgAAAE8AAABOCAAAAABEAxT/AAADZElEQVR42s3YT2viQBQA8Jkxf0jS1lhpF5GyRaoU
T7nszUqhvXSh4EnYD9Lv0IN3T/0G3grtpQuF9VJ6yW2LLdJSRYpYE5eYmj+TPcRYtVY0Mws7J0HyY4b3ZubNgx6g
OhBdDjDz/8aDgWU5LvYARBGG43gehfY8q2/o9fpzq6MbNmClaDyxlUpFJZGDITzH6D6o6l3HtGx7OD+W5YT4rqLs
xKRPP4Mz4+HZvWa1qr72TTz5P0SCuK7kcsk1Fi7uOd37q+uaZuLZIRTkzP5hOsYs6OE/jxeXNc36PJMgJ2eOvm+v
ogU8z279PL9t2/PzErIb344PEjMW7U0OV785SYsLZCUS0yc3ujv1uTfluS+VYiKyWOpGEsXKizvXcxrlvLzwlkFy
vtxw5njOU0kR4eKbC4pK6cn51HOeTrP8ctuVz55OgmOe2yhluWX3P5ctNdyZnvtSVvjlDxReKY8HZeRhvZIXw5xQ
Yr6i44/e4KYowzAelIs3g5EXbELcqvzqhTqrvd6vr1+20NT+0M7SkbBnciR9pgXzG7rO43nTDeu5zfNHZ+L+8LoX
t2/hL42324uuN+7Z95dtHN7D7ct7e9zrXdVsklvNrl31xjynea0R3cOedt103j2jWrPIrl2rVjVGntetaoRlgqdV
/YggAID1oJqkdYGpPliB11dfMamHX9V+4Bn+T7LRV42hh/U7k9wz73Tse4N6B5N7uFMfBJ5JoQj0zMCzni1AYfgM
AsBq2TQ8uzX0nA4dr+P4nqu7NDyfQQBgA9PwfAYB4NlUanyfoV3fIwAgC2lIPoMAQBKVSfoMAiASjdDwfAYBwMRZ
Gh4bZ3yPS9DxEtzQ2+JoeD6DAOBTAoUAQyHFB16cQoBRPPBQdFcg94Td6DBfgKSI5J6oSMF9JCrrxAtG6/6kEACA
21GIFywoO1zgwVhOJowwlHMxOKpfpFyGMAW5TE56r4eY5D7ZBKG8n2TG6r+1wwzRnmMzh2vj9SSbPtogCDHaOEqz
E/W9rRYIclAsqPZkfc9sHyfDvxeSx9vMVH9o9aCwGXLFaLNwsPrhvU/pvUX7PThqosCVvXbv92D592rmx94KnNXf
oPyepv7ep96PoN4vod7PIe830e6H/fN+Hf1+Iv1+J/V+bPh+MfTo9rPhf96//wuMelWEAnMqjAAAAABJRU5ErkJg
gg==
"""


def load_mask(data):
    return Image.open(io.BytesIO(base64.b64decode(data))).convert("L")


def white_layer(alpha):
    layer = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
    layer.putalpha(alpha)
    return layer


def compose(motif, pos):
    """Places an RGBA motif at pos (canvas coordinates) into the template."""
    icon = Image.new("RGBA", CANVAS, (255, 255, 255, 255))
    placed = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    placed.paste(motif, pos)
    icon.alpha_composite(placed)
    icon.alpha_composite(white_layer(load_mask(INNER_CIRCLE_MASK)))
    icon.alpha_composite(white_layer(load_mask(WHITE_HALO)))

    shape = load_mask(WHITE_CIRCLE)
    icon.putalpha(shape)
    outside = shape.point(lambda a: 255 if a == 0 else 0)
    icon.paste((0, 0, 0, 0), mask=outside)
    return icon


def fit_motif(image, size, fit):
    """Scales so the short side (cover) or the long side (contain) equals size."""
    w, h = image.size
    side = min(w, h) if fit == "cover" else max(w, h)
    factor = size / side
    new_size = (max(1, round(w * factor)), max(1, round(h * factor)))
    return image.resize(new_size, Image.LANCZOS)


def make_icon(path, size=DEFAULT_SIZE, fit="cover", offset=(0, 0)):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
    motif = fit_motif(image, size, fit)
    pos = tuple(
        math.floor(CENTER[i] - motif.size[i] / 2 + 0.5) + offset[i] for i in range(2)
    )
    return compose(motif, pos)


def main():
    parser = argparse.ArgumentParser(description="Creates a map icon (79x78 PNG) from an image.")
    parser.add_argument("input", type=Path, help="source image")
    parser.add_argument("output", type=Path, nargs="?", help="output file (default: <source>_icon.png)")
    parser.add_argument("--fit", choices=["cover", "contain"], default="cover",
                        help="cover: fill the circle, crop the overflow (default); "
                             "contain: show the whole image, the rest stays white")
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE,
                        help=f"motif size in pixels (default: {DEFAULT_SIZE}; visible circle: 72)")
    parser.add_argument("--offset", type=int, nargs=2, default=(0, 0), metavar=("X", "Y"),
                        help="shift the motif by X/Y pixels")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
    args = parser.parse_args()

    output = args.output or args.input.with_name(args.input.stem + "_icon.png")
    if output.suffix.lower() != ".png":
        parser.error("The output file must end in .png.")
    if output.exists() and not args.force:
        sys.exit(f"{output} already exists (use --force to overwrite).")

    make_icon(args.input, args.size, args.fit, tuple(args.offset)).save(output)
    print(output)


if __name__ == "__main__":
    main()
