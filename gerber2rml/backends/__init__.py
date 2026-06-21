"""Machine backends: name -> render function (the pluggable seam)."""
from gerber2rml.backends import srm20

BACKENDS = {"Roland SRM-20": srm20.render}
