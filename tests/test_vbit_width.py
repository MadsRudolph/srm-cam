"""V-bit width test card generator (examples.vbit_width)."""
from gerber2rml.examples.vbit_width import BOARD_H, BOARD_W, WIDTHS, write_coupon
from gerber2rml.loader import load_board


def test_card_round_trips_through_loader(tmp_path):
    folder = write_coupon(tmp_path)
    board = load_board(folder, mirror=False)
    minx, miny, maxx, maxy = board.outline.bounds
    assert abs((maxx - minx) - BOARD_W) < 0.5
    assert abs((maxy - miny) - BOARD_H) < 0.5
    assert not board.copper.is_empty
    assert len(board.holes) == 2


def test_tracks_have_stepped_widths(tmp_path):
    """Each design width must survive as a distinct copper strip."""
    folder = write_coupon(tmp_path)
    board = load_board(folder, mirror=False)
    from shapely.geometry import LineString
    # probe a vertical line through the track midspan; intersection lengths
    # are the as-designed track widths
    mid = board.copper.intersection(LineString([(13.0, 0), (13.0, BOARD_H)]))
    lengths = sorted((g.length for g in getattr(mid, "geoms", [mid])))
    assert len(lengths) == len(WIDTHS)
    for got, want in zip(lengths, sorted(WIDTHS)):
        assert abs(got - want) < 0.01


def test_files_written(tmp_path):
    folder = write_coupon(tmp_path)
    names = {p.name for p in folder.iterdir()}
    assert "vbit-B_Cu.gbr" in names and "vbit-Edge_Cuts.gbr" in names
    assert "vbit.drl" in names and "README.txt" in names
