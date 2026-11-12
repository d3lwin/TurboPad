"""Generate the AppImage icon from the bundled controller artwork."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "ds4_front.png"
OUTPUT = ROOT / "packaging" / "turbopad.png"
SIZE = 512
PADDING = 26


def build() -> None:
    art = Image.open(SOURCE).convert("RGBA")
    bbox = art.getbbox()
    if bbox:
        art = art.crop(bbox)

    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    plate = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)
    draw.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=104, fill="#101820")
    draw.rounded_rectangle(
        (3, 3, SIZE - 4, SIZE - 4),
        radius=101,
        outline="#223044",
        width=4,
    )
    icon.alpha_composite(plate)

    scale = (SIZE - PADDING * 2) / art.width
    art = art.resize(
        (round(art.width * scale), round(art.height * scale)),
        Image.LANCZOS,
    )
    icon.alpha_composite(
        art,
        ((SIZE - art.width) // 2, (SIZE - art.height) // 2),
    )
    icon.save(OUTPUT, optimize=True)
    print(f"wrote {OUTPUT} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    build()
