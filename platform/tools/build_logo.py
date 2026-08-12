"""Rebuild the raster logo assets from the brand SVG.

    python tools/build_logo.py

Excel and PowerPoint cannot embed SVG, so the wordmark is rasterised once here
rather than at report time. Run this only when the source SVG changes.

Produces, in platform/assets/:
    levista_logo.png        brown on white  — general use
    levista_logo_white.png  white,  transparent — dark slide and header fills
    levista_logo_brown.png  brown, transparent — light backgrounds
    levista_mark.svg/.png   the swirl glyph alone, for tight spaces
"""
import re
from pathlib import Path

from PIL import Image
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT.parent / "Levista_Coffee_Logo_Large_Sharp.svg"
ASSETS = ROOT / "assets"
SCALE = 3.0


def rasterise(svg_path: Path, out: Path, scale: float = SCALE) -> Image.Image:
    drawing = svg2rlg(str(svg_path))
    drawing.width *= scale
    drawing.height *= scale
    drawing.scale(scale, scale)
    renderPM.drawToFile(drawing, str(out), fmt="PNG", bg=0xFFFFFF)
    return Image.open(out)


def recolour(image: Image.Image, rgb: tuple) -> Image.Image:
    """Ink -> rgb, paper -> transparent, keeping anti-aliased edges smooth."""
    out = Image.new("RGBA", image.size)
    out.putdata([(*rgb, 255 - min(px[0], px[1], px[2]))
                 for px in image.convert("RGBA").getdata()])
    return out


def main():
    ASSETS.mkdir(exist_ok=True)
    if not SOURCE.exists():
        raise SystemExit(f"Brand SVG not found: {SOURCE}")

    full = ASSETS / "levista_logo.png"
    image = rasterise(SOURCE, full).convert("RGB")
    # Trim the SVG's white margin so the wordmark sits flush against its box.
    bounds = Image.eval(image.convert("L"), lambda p: 255 - p).getbbox()
    image = image.crop(bounds)
    image.save(full)

    recolour(image, (0xFF, 0xFF, 0xFF)).save(ASSETS / "levista_logo_white.png")
    recolour(image, (0x39, 0x22, 0x15)).save(ASSETS / "levista_logo_brown.png")

    # The swirl alone, for the collapsed sidebar rail and other tight spaces.
    glyph = re.search(r'<path class="cls-2" d="([^"]+)"', SOURCE.read_text(encoding="utf-8"))
    if glyph:
        mark = ASSETS / "levista_mark.svg"
        mark.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="2620 1160 520 990">'
            f'<path fill="#392215" d="{glyph.group(1)}"/></svg>', encoding="utf-8")
        rasterise(mark, ASSETS / "levista_mark.png", scale=4.0)

    for name in sorted(p.name for p in ASSETS.glob("levista*")):
        print(f"  {name}")
    print(f"Wrote {ASSETS}")


if __name__ == "__main__":
    main()
