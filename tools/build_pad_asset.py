"""Build the high-resolution DualShock 4 artwork used by the input map.

The source is the Wikimedia Commons "Dualshock 4 Layout.svg" by Tokyoship
(CC BY 3.0).  This script recolours the vector artwork for TurboPad's dark
theme and rasterises it, adding a soft drop shadow and a little top lighting.

Run from the project root:

    .venv/bin/python tools/build_pad_asset.py
"""

from __future__ import annotations

import io
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import cairosvg
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "ds4_reference.svg"
OUTPUT = ROOT / "assets" / "ds4_front.png"

# 1x view box.  The controller artwork is placed at PAD_OFFSET inside this
# canvas; the extra room is used for the shadow and the shoulder read-outs.
VIEW_W, VIEW_H = 620, 430
PAD_W, PAD_H = 600, 400
PAD_OFFSET = 10
SCALE = 3

# Palette tuned for the app's dark surfaces.
BODY = "#252a33"
INSET = "#15191f"
EDGE = "#6d788a"
INSET_EDGE = "#596475"
DETAIL = "#090b0f"
DOT = "#343b46"
PS_LOGO = "#e9f1ff"
LABEL = "#a3b1c6"
ARROW = "#aebbd0"
LIGHTBAR_DIM = "#1d5c78"

CROSS = "#5ea8ff"
CIRCLE = "#ff7082"
SQUARE = "#ff8ccd"
TRIANGLE = "#62edbe"

FILL_MAP = {
    "#cccccc": BODY,
    "#000000": DETAIL,
    "#37abc8": LIGHTBAR_DIM,
}
STROKE_MAP = {
    "#000000": EDGE,
}


def parse_style(value: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for chunk in (value or "").split(";"):
        if ":" not in chunk:
            continue
        key, val = chunk.split(":", 1)
        result[key.strip()] = val.strip()
    return result


def write_style(element: ET.Element, style: dict[str, str]) -> None:
    element.set("style", ";".join(f"{key}:{value}" for key, value in style.items()))


def paint(element: ET.Element, **changes: str) -> None:
    style = parse_style(element.get("style"))
    for key, value in changes.items():
        style[key] = value
    write_style(element, style)


def recolour(root: ET.Element) -> None:
    # First pass: translate every literal fill/stroke, including group styles
    # that children may inherit.
    for element in root.iter():
        style = parse_style(element.get("style"))
        fill = style.get("fill", element.get("fill"))
        stroke = style.get("stroke", element.get("stroke"))
        if fill in FILL_MAP:
            style["fill"] = FILL_MAP[fill]
        if stroke in STROKE_MAP:
            style["stroke"] = STROKE_MAP[stroke]
        if style:
            element.attrib.pop("fill", None)
            element.attrib.pop("stroke", None)
            write_style(element, style)

    # Recessed controls read as physical buttons against the body.
    for element_id in (
        "path3038",
        "path3038-1",
        "path3038-4",
        "path3038-6",
        "path2995",
        "path2995-7",
        "path3840",
        "path4031-4",
        "path4031-3",
        "path4031",
        "path4031-4-7",
        "path4031-3-2",
        "path4031-7",
        "path3190",
        "rect3842-7",
    ):
        paint_by_id(root, element_id, fill=INSET, stroke=INSET_EDGE)

    # The D-pad's four rounded keys are a scaled group; the small triangles on
    # the outside are its direction markers.
    for element_id in ("rect3996", "rect3996-2", "rect3996-3", "rect3996-7"):
        paint_by_id(root, element_id, fill=ARROW, stroke="none")

    # Face-button glyphs get authentic DualShock 4 colours.
    paint_by_id(root, "path4532", fill="none", stroke=CROSS)
    paint_by_id(root, "path4532-0", fill="none", stroke=CROSS)
    paint_by_id(root, "path4552", fill=INSET, stroke=CIRCLE)
    paint_by_id(root, "rect4554", fill=INSET, stroke=SQUARE)
    paint_by_id(root, "path4554-1", fill=INSET, stroke=TRIANGLE)

    # Touchpad speckle and light bar.
    paint_by_id(root, "path3842-4-9", fill=DOT, stroke="none")
    paint_by_id(root, "path3235", fill=LIGHTBAR_DIM, stroke="none")

    # Groups whose children should all share one treatment.
    paint_group(root, "g6246", fill=INSET, stroke=INSET_EDGE)
    paint_group(root, "layer1-0", fill=PS_LOGO, stroke="none")
    paint_group(root, "text4575", fill=LABEL, stroke="none")
    paint_group(root, "text4575-2", fill=LABEL, stroke="none")
    paint_group(root, "g3982", fill=DETAIL, stroke="none")


def paint_by_id(root: ET.Element, element_id: str, **changes: str) -> None:
    element = next((item for item in root.iter() if item.get("id") == element_id), None)
    if element is not None:
        paint(element, **changes)


def paint_group(root: ET.Element, group_id: str, **changes: str) -> None:
    group = next((item for item in root.iter() if item.get("id") == group_id), None)
    if group is None:
        return
    for child in group.iter():
        if child.tag.split("}")[-1] in {"path", "rect", "circle", "ellipse"}:
            paint(child, **changes)


def shade(image: Image.Image) -> Image.Image:
    """Add gentle top lighting and a darker lower edge to the flat vector art."""

    width, height = image.size
    light = Image.new("RGBA", image.size, (0, 0, 0, 0))
    pixels = light.load()
    for y in range(height):
        t = y / max(1, height - 1)
        if t < 0.45:
            alpha = int(24 * (1.0 - t / 0.45))
            colour = (255, 255, 255, alpha)
        else:
            alpha = int(34 * ((t - 0.45) / 0.55))
            colour = (0, 0, 0, alpha)
        for x in range(width):
            pixels[x, y] = colour
    shaded = Image.alpha_composite(image, light)
    shaded.putalpha(image.split()[3])
    return shaded


def build() -> None:
    tree = ET.parse(SOURCE)
    root = tree.getroot()
    recolour(root)
    data = ET.tostring(root, encoding="utf-8")

    png = cairosvg.svg2png(
        bytestring=data,
        output_width=PAD_W * SCALE,
        output_height=PAD_H * SCALE,
        background_color=None,
    )
    art = Image.open(io.BytesIO(png)).convert("RGBA")

    offset = PAD_OFFSET * SCALE
    canvas = Image.new("RGBA", (VIEW_W * SCALE, VIEW_H * SCALE), (0, 0, 0, 0))

    shadow_mask = art.split()[3].filter(ImageFilter.GaussianBlur(6 * SCALE))
    shadow = Image.new("RGBA", art.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_mask.point(lambda value: int(value * 0.46)))
    canvas.alpha_composite(shadow, (offset, offset + 7 * SCALE))

    canvas.alpha_composite(shade(art), (offset, offset))

    canvas.save(OUTPUT, optimize=True)
    print(f"wrote {OUTPUT} ({canvas.width}x{canvas.height})")


if __name__ == "__main__":
    try:
        build()
    except Exception as exc:  # pragma: no cover - build helper
        print(f"error: {exc}", file=sys.stderr)
        raise
