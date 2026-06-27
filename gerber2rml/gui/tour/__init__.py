"""First-launch guided tour (coachmark overlay).

A gated walkthrough of the core milling workflow — load → preset → preview →
placement → export — plus opt-in mini-tours for the advanced features
(double-sided, bed leveling, rework). See :mod:`gerber2rml.gui.tour.controller`.
"""
from gerber2rml.gui.tour.controller import TourController

__all__ = ["TourController"]
