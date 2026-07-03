import numpy as np
import pytest
from gerber2rml.engine.photofit import (fit_homography, apply_homography,
                                        residuals, warp_photo)


def _true_h():
    # a plausible phone shot: rotation + perspective + scale + offset
    return np.array([[0.021, 0.004, -14.0],
                     [-0.003, -0.0195, 55.0],
                     [1.2e-5, -8e-6, 1.0]])


def test_fit_recovers_exact_homography():
    H = _true_h()
    rng = np.random.default_rng(7)
    photo = rng.uniform(100, 3000, size=(6, 2))
    machine = apply_homography(H, photo)
    Hf = fit_homography(photo, machine)
    r = residuals(Hf, photo, machine)
    assert r.max() < 1e-8


def test_fit_least_squares_averages_noise():
    H = _true_h()
    rng = np.random.default_rng(3)
    photo = rng.uniform(100, 3000, size=(8, 2))
    machine = apply_homography(H, photo) + rng.normal(0, 0.05, size=(8, 2))
    Hf = fit_homography(photo, machine)
    r = residuals(Hf, photo, machine)
    assert r.max() < 0.25          # noise absorbed, not amplified


def test_fit_rejects_bad_input():
    with pytest.raises(ValueError):
        fit_homography([(0, 0), (1, 1), (2, 2)], [(0, 0), (1, 1), (2, 2)])
    with pytest.raises(ValueError):                 # collinear
        fit_homography([(0, 0), (1, 0), (2, 0), (3, 0)],
                       [(0, 0), (1, 0), (2, 0), (3, 0)])


def test_warp_places_photo_pixel_at_machine_xy():
    # identity-ish H: photo pixel (u, v) -> machine (u/10, (H-v)/10) mm
    img = np.zeros((100, 100, 3), np.uint8)
    img[19:22, 69:72] = (255, 0, 0)                 # red 3x3 at u=70, v=20
    photo = [(0, 99), (99, 99), (99, 0), (0, 0)]    # corners
    machine = [(0, 0), (9.9, 0), (9.9, 9.9), (0, 9.9)]
    H = fit_homography(photo, machine)
    rgba, extent = warp_photo(img, H, (0, 0, 10, 10), px_per_mm=10.0)
    assert extent == (0, 10, 0, 10)
    # expected machine pos of the red pixel: x = 7.0, y = (99-20)/10 = 7.9
    j = int(7.9 * 10); i = int(7.0 * 10)
    patch = rgba[j - 2:j + 3, i - 2:i + 3]
    assert patch[..., 0].max() > 150                # red landed there
    assert rgba[:98, :98, 3].min() == 255           # covered up to 9.9 mm
    assert rgba[-1, -1, 3] == 0                     # outside the 9.9 mm photo


def test_warp_alpha_zero_outside_photo():
    img = np.full((50, 50, 3), 200, np.uint8)
    photo = [(0, 49), (49, 49), (49, 0), (0, 0)]
    machine = [(0, 0), (5, 0), (5, 5), (0, 5)]      # photo covers 0..5 mm only
    H = fit_homography(photo, machine)
    rgba, _ = warp_photo(img, H, (0, 0, 10, 10), px_per_mm=4.0)
    assert rgba[2, 2, 3] == 255                     # inside
    assert rgba[-1, -1, 3] == 0                     # outside the photo
