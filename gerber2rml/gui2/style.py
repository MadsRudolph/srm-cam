"""The application stylesheet, rendered from :mod:`theme`.

Rendered with :class:`string.Template` (``$NAME``) rather than ``str.format``,
because QSS is full of braces and every one would need escaping.

What is deliberately NOT here: letter-spacing and capitalisation. Qt's QSS
subset has neither, so the tracked all-caps eyebrow labels are set through
:func:`theme.font` in code. Anything that must be a *font decision* rather than
a colour decision lives there for the same reason.

Object names used as selectors are declared as constants at the bottom so a
rename is a code change and not a silent no-op — a QSS rule pointed at an
object name nobody sets is invisible, which is the failure mode this file is
most exposed to.
"""
from string import Template

from gerber2rml.gui2 import theme

_QSS = Template("""
/* ---------------------------------------------------------------- ground */
QWidget {
    background: $BASE;
    color: $TEXT;
    font-family: "$BODY";
    font-size: ${SIZE_BODY}px;
}
QMainWindow, QDialog { background: $BASE; }
QWidget:disabled { color: $TEXT_4; }

QToolTip {
    background: $PANEL_HI;
    color: $TEXT;
    border: 1px solid $RULE_HI;
    border-left: 2px solid $PRIMARY_LO;
    padding: 7px 10px;
    font-size: ${SIZE_SMALL}px;
}

/* ---------------------------------------------------------------- panels */
QFrame#panel      { background: $PANEL;    border: none; }
QFrame#panelSunk  { background: $SUNK;     border: none; }
QFrame#card {
    background: $PANEL_HI;
    border: 1px solid $RULE;
    border-radius: ${RADIUS}px;
}
QFrame#cardQuiet {
    background: transparent;
    border: 1px solid $RULE;
    border-radius: ${RADIUS}px;
}
QFrame#rule       { background: $RULE; border: none; max-height: 1px; }
QFrame#ruleStrong { background: $RULE_STRONG; border: none; max-height: 1px; }
QFrame#ruleV      { background: $RULE; border: none; max-width: 1px; }

/* ------------------------------------------------------------------ text */
QLabel { background: transparent; }
QLabel#eyebrow  { color: $TEXT_3; }
QLabel#title    { color: $TEXT; }
QLabel#head     { color: $TEXT; }
QLabel#hint     { color: $TEXT_3; font-size: ${SIZE_SMALL}px; }
QLabel#mono     { color: $TEXT_2; font-family: "$MONO"; }
QLabel#monoHi   { color: $TEXT;   font-family: "$MONO"; }
QLabel#value    { color: $TEXT; }
QLabel#unit     { color: $TEXT_3; font-size: ${SIZE_MICRO}px; }
QLabel#empty    { color: $TEXT_4; }

/* --------------------------------------------------------------- buttons */
/* Three weights, and they mean three different things:
   #primary  the one thing this panel is for      (near-white fill)
   (default) everything else                      (raised, neutral)
   #danger   stops work, or cannot be undone      (red)                     */
QPushButton {
    background: $RAISED;
    color: $TEXT;
    border: 1px solid $RULE_HI;
    border-radius: ${RADIUS}px;
    padding: 7px 14px;
    font-family: "$LABEL";
    font-size: ${SIZE_SMALL}px;
}
QPushButton:hover   { background: $RAISED_HI; border-color: $RULE_STRONG; }
QPushButton:pressed { background: $PANEL_HI; }
QPushButton:disabled {
    background: $SUNK; color: $TEXT_4; border-color: $RULE;
}
QPushButton:focus { border: 1px solid $FOCUS; }

QPushButton#primary {
    background: $PRIMARY;
    color: $ON_LIGHT;
    border: 1px solid $PRIMARY;
    padding: 9px 18px;
    font-size: ${SIZE_BODY}px;
}
QPushButton#primary:hover   { background: $PRIMARY_HI; border-color: $PRIMARY_HI; }
QPushButton#primary:pressed { background: $PRIMARY_LO; }
QPushButton#primary:disabled {
    background: $RAISED; color: $TEXT_4; border-color: $RULE;
}

QPushButton#danger {
    background: $DANGER_FILL;
    color: $DANGER_HI;
    border: 1px solid $DANGER_EDGE;
}
QPushButton#danger:hover   { background: $DANGER_LO; color: $TEXT; border-color: $DANGER; }
QPushButton#danger:pressed { background: $DANGER; color: $ON_LIGHT; }
QPushButton#danger:disabled {
    background: $SUNK; color: $TEXT_4; border-color: $RULE;
}

/* The stop control. It is the only object in the application with this
   treatment, so that it can never be mistaken for anything else. It is also
   never styled as disabled: see machine.py for why it stays live. */
QPushButton#stop {
    background: $DANGER;
    color: $ON_LIGHT;
    border: 1px solid $DANGER_HI;
    border-radius: ${RADIUS}px;
    padding: 10px 22px;
    font-family: "$DISPLAY";
    font-size: ${SIZE_HEAD}px;
}
QPushButton#stop:hover   { background: $DANGER_HI; }
QPushButton#stop:pressed { background: $DANGER_LO; }

QPushButton#ghost {
    background: transparent;
    border: 1px solid transparent;
    color: $TEXT_2;
    padding: 5px 9px;
}
QPushButton#ghost:hover { background: $HOVER; color: $TEXT; border-color: $RULE_HI; }
QPushButton#ghost:disabled { color: $TEXT_4; background: transparent; }

QPushButton#link {
    background: transparent; border: none; color: $TEXT_2;
    padding: 2px 0; text-align: left;
    font-family: "$BODY"; font-size: ${SIZE_SMALL}px;
}
QPushButton#link:hover { color: $TEXT; }

/* A jog key. Square, monospaced, meant to be hit repeatedly. */
QPushButton#key {
    background: $RAISED;
    border: 1px solid $RULE_HI;
    color: $TEXT;
    font-family: "$MONO";
    font-size: ${SIZE_HEAD}px;
    padding: 0;
}
QPushButton#key:hover   { background: $RAISED_HI; border-color: $FOCUS; }
QPushButton#key:pressed { background: $LIVE_FILL; border-color: $LIVE; }
QPushButton#key:disabled { background: $SUNK; color: $TEXT_4; border-color: $RULE; }

QPushButton:checked { background: $SELECT; border-color: $SELECT_EDGE; color: $TEXT; }

/* -------------------------------------------------------- segmented pick */
/* One row, one choice. Used for the stage frame switch, and nowhere else —
   the operation is chosen in the traveller and only in the traveller. */
QPushButton#seg {
    background: transparent;
    border: 1px solid transparent;
    border-radius: ${RADIUS_CHIP}px;
    color: $TEXT_3;
    padding: 5px 12px;
    font-family: "$LABEL";
    font-size: ${SIZE_SMALL}px;
}
QPushButton#seg:hover   { color: $TEXT_2; background: $HOVER; }
QPushButton#seg:checked { background: $RAISED; color: $TEXT; border-color: $RULE_HI; }

/* ------------------------------------------------------------ text entry */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: $SUNK;
    color: $TEXT;
    border: 1px solid $RULE_HI;
    border-radius: ${RADIUS}px;
    padding: 6px 9px;
    selection-background-color: $SELECT;
    selection-color: $TEXT;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border-color: $FOCUS;
    background: $INK;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled { background: $SUNK; color: $TEXT_4; border-color: $RULE; }
QLineEdit#mono, QPlainTextEdit#mono, QTextEdit#mono {
    font-family: "$MONO"; font-size: ${SIZE_SMALL}px;
}
/* A number the machine will act on is set in the machine face, so that a value
   you typed and a value the machine reported look like the same kind of fact. */
QSpinBox, QDoubleSpinBox { font-family: "$MONO"; }

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: $RAISED; border: none; width: 15px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: $RAISED_HI; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    width: 0; height: 0; border-left: 3px solid transparent;
    border-right: 3px solid transparent; border-bottom: 4px solid $TEXT_2;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    width: 0; height: 0; border-left: 3px solid transparent;
    border-right: 3px solid transparent; border-top: 4px solid $TEXT_2;
}

QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow {
    width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid $TEXT_2;
    margin-right: 7px;
}
QComboBox QAbstractItemView {
    background: $PANEL_HI;
    border: 1px solid $RULE_HI;
    selection-background-color: $SELECT;
    selection-color: $TEXT;
    outline: none;
    padding: 3px;
}

/* -------------------------------------------------------------- checkbox */
QCheckBox, QRadioButton { background: transparent; spacing: 8px; padding: 2px 0; }
QCheckBox::indicator, QRadioButton::indicator { width: 15px; height: 15px; }
QCheckBox::indicator {
    background: $SUNK; border: 1px solid $RULE_STRONG; border-radius: ${RADIUS_CHIP}px;
}
QCheckBox::indicator:hover { border-color: $FOCUS; }
/* Checked is a filled block rather than a tick glyph: Qt would need a resource
   file for the tick, and a missing resource fails silently to an EMPTY box —
   i.e. it looks exactly like unchecked. A fill cannot fail that way. */
QCheckBox::indicator:checked {
    background: $PRIMARY; border-color: $PRIMARY;
}
QCheckBox::indicator:checked:hover { background: $PRIMARY_HI; }
QCheckBox::indicator:disabled { background: $SUNK; border-color: $RULE; }
QRadioButton::indicator {
    background: $SUNK; border: 1px solid $RULE_STRONG; border-radius: 7px;
}
QRadioButton::indicator:checked { background: $PRIMARY; border: 4px solid $SUNK; }

/* ---------------------------------------------------------------- tables */
QTableWidget, QTableView, QTreeView, QListWidget {
    background: $SUNK;
    alternate-background-color: $PANEL;
    border: 1px solid $RULE;
    border-radius: ${RADIUS}px;
    gridline-color: $RULE;
    selection-background-color: $SELECT;
    selection-color: $TEXT;
    outline: none;
    font-family: "$MONO";
    font-size: ${SIZE_SMALL}px;
}
QHeaderView::section {
    background: $PANEL;
    color: $TEXT_3;
    border: none;
    border-bottom: 1px solid $RULE_HI;
    padding: 6px 8px;
    font-family: "$LABEL";
    font-size: ${SIZE_LABEL}px;
}
QTableWidget::item, QTableView::item { padding: 3px 6px; }
QTableCornerButton::section { background: $PANEL; border: none; }

/* -------------------------------------------------------------- scrolling */
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 0;
}
QScrollBar::handle:vertical {
    background: $RAISED; border-radius: 5px; min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: $RAISED_HI; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal {
    background: $RAISED; border-radius: 5px; min-width: 32px;
}
QScrollBar::handle:horizontal:hover { background: $RAISED_HI; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ------------------------------------------------------------------ menu */
QMenuBar {
    background: $BASE; color: $TEXT_2; border-bottom: 1px solid $RULE;
    font-family: "$LABEL"; font-size: ${SIZE_SMALL}px; padding: 2px 6px;
}
QMenuBar::item { background: transparent; padding: 6px 11px; border-radius: ${RADIUS}px; }
QMenuBar::item:selected { background: $RAISED; color: $TEXT; }
QMenu {
    background: $PANEL_HI; border: 1px solid $RULE_HI; padding: 5px;
    font-size: ${SIZE_SMALL}px;
}
QMenu::item { padding: 7px 26px 7px 14px; border-radius: ${RADIUS}px; }
QMenu::item:selected { background: $SELECT; }
QMenu::item:disabled { color: $TEXT_4; }
QMenu::separator { height: 1px; background: $RULE; margin: 5px 8px; }

/* --------------------------------------------------------------- progress */
QProgressBar {
    background: $SUNK; border: 1px solid $RULE; border-radius: ${RADIUS_CHIP}px;
    height: 5px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: $PRIMARY_LO; border-radius: ${RADIUS_CHIP}px; }

/* --------------------------------------------------------------- splitter */
QSplitter::handle { background: $RULE; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QSplitter::handle:hover { background: $FOCUS; }

/* ---------------------------------------------------------------- dialogs */
QDialogButtonBox QPushButton { min-width: 88px; }
QMessageBox { background: $PANEL; }
QMessageBox QLabel { color: $TEXT; }
""")


def stylesheet():
    """The rendered QSS. Every ``$NAME`` resolves to a :mod:`theme` token."""
    values = {k: v for k, v in vars(theme).items()
              if k.isupper() and isinstance(v, (str, int, float))}
    values.update(
        BODY=theme.BODY_FAMILY[0],
        LABEL=theme.LABEL_FAMILY[0],
        DISPLAY=theme.DISPLAY_FAMILY[0],
        MONO=theme.MONO_FAMILY[0],
        SIZE_BODY=round(theme.SIZE_BODY),
        SIZE_SMALL=round(theme.SIZE_SMALL),
        SIZE_HEAD=round(theme.SIZE_HEAD),
        SIZE_LABEL=round(theme.SIZE_LABEL),
        SIZE_MICRO=round(theme.SIZE_MICRO),
    )
    return _QSS.substitute(values)


STYLESHEET = stylesheet()
