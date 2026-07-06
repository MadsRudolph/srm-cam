"""Auto-crop to the copper stock (engine.autocrop) — synthetic scenes."""
import numpy as np

from gerber2rml.engine.autocrop import copper_bbox, crop_to_copper

RNG = np.random.default_rng(7)

COPPER = (185, 142, 128)     # muted pink-brown, like real milled stock
WOOD = (196, 168, 112)       # spoilboard tan (yellower: big green-blue gap)
GREY = (70, 72, 75)          # machine body


def scene(w=800, h=600, board=None, wood=None, bg=GREY, noise=6):
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = bg
    if wood:
        x0, y0, x1, y1 = wood
        img[y0:y1, x0:x1] = WOOD
    if board:
        x0, y0, x1, y1 = board
        img[y0:y1, x0:x1] = COPPER
    img = img.astype(np.int16) + RNG.integers(-noise, noise, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def test_finds_board_against_machine():
    img = scene(board=(160, 120, 680, 500))
    box = copper_bbox(img)
    assert box is not None
    x0, y0, x1, y1 = box
    # within a few percent of the true rectangle (normalized coords)
    assert abs(x0 - 160 / 800) < 0.05 and abs(x1 - 680 / 800) < 0.05
    assert abs(y0 - 120 / 600) < 0.05 and abs(y1 - 500 / 600) < 0.05


def test_board_on_wood_spoilboard_crops_to_copper_not_wood():
    img = scene(wood=(80, 60, 760, 560), board=(160, 120, 680, 500))
    box = copper_bbox(img)
    assert box is not None
    x0, y0, x1, y1 = box
    assert x0 > 80 / 800 + 0.02 and x1 < 760 / 800 - 0.02
    assert y0 > 60 / 600 + 0.02 and y1 < 560 / 600 - 0.02


def test_no_board_no_crop():
    assert copper_bbox(scene()) is None                       # machine only
    assert copper_bbox(scene(wood=(80, 60, 760, 560))) is None  # wood only


def test_already_cropped_left_alone():
    img = scene(board=(0, 0, 800, 600))                       # wall-to-wall
    out, cropped = crop_to_copper(img)
    assert not cropped
    assert out.shape == img.shape


def test_crop_to_copper_returns_cropped_array():
    img = scene(board=(160, 120, 680, 500))
    out, cropped = crop_to_copper(img)
    assert cropped
    assert out.shape[0] < img.shape[0] and out.shape[1] < img.shape[1]
    # the crop is mostly copper
    r = out[..., 0].astype(int)
    g = out[..., 1].astype(int)
    assert ((r - g) >= 8).mean() > 0.7


def test_dust_speck_does_not_drag_box():
    img = scene(board=(160, 120, 680, 500))
    img[20:24, 20:24] = COPPER                # a stray coppery speck far away
    box = copper_bbox(img)
    x0, y0, _x1, _y1 = box
    assert x0 > 0.1 and y0 > 0.1              # still anchored on the board


def test_rgba_input_ok():
    img = scene(board=(160, 120, 680, 500))
    rgba = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    assert copper_bbox(rgba) is not None
