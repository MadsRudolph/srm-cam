"""Generate the KiCad plugin's toolbar icon.

    python packaging/gen_plugin_icon.py

26 x 26 is the size pcbnew's ActionPlugin toolbar expects. Drawn on integer
pixel boundaries rather than scaled down from something larger, because a 1 px
outline that lands between pixels turns to grey mush at this size.

The mark is the plugin's own job: the outer rectangle is the machine's build
area, the solid one inside it is your board. Two tones only — it has to stay
legible against both KiCad's light and dark toolbars, so neither is near white
or near black.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "kicad-plugin" / "icon.png"

SIZE = 26
ENVELOPE = (110, 122, 136, 255)   # slate — the machine
BOARD = (184, 115, 51, 255)       # copper — the board


def main():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # the build area: 203.2 x 152.4 is close to 4:3, so is this
    d.rectangle([2, 4, 23, 21], outline=ENVELOPE, width=1)
    # the board, sitting inside it with hold-down margin around it
    d.rectangle([8, 9, 17, 16], fill=BOARD)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"wrote {OUT}  ({SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
