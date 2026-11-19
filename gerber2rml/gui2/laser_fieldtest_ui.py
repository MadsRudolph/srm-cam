"""The field test on the laser page (engine/laser_fieldtest.py): loaded as a
traces job to place on a spare sheet like a board, and cut with the page's
recipe - each ladder height as its own band, the head moved for it."""
from gerber2rml.engine import laser_fieldtest as ft


def load(page):
    """Put the field test on the page in place of the job."""
    art, heights = ft.field_test_art()
    page.show_job(art, "Field test")
    page._field_heights = heights
    page._say("Field test loaded: drag it onto a spare sheet (160 x 100), "
              "Autofocus, then Etch. " + ft.key())


def active(page):
    """The page's job is the field test, with the heights to cut it at."""
    art = getattr(page, "_source", None)       # the job as it was given
    return (art is not None and getattr(art, "note", None) == ft.NOTE
            and getattr(page, "_field_heights", None) is not None)


def zones(page, only=None):
    """``[(dz, {aperture index})]`` for the run."""
    return ft.groups(page._field_heights, only)
