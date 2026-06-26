# Settings/Preview Layout Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stop the settings panel from clipping fields / needing constant divider drags — fit-width panel, preview absorbs resizing, plus a collapse toggle.

**Architecture:** A focused change to the `settings_container` / `QSplitter` block in `gerber2rml/gui/app.py` and one toggle button on the machine bar.

**Tech Stack:** PySide6, pytest.

## Global Constraints

- No new dependencies. Commits read like a developer wrote them (no AI mention).
- Tests in `tests/test_window.py`, offscreen (already configured).

---

### Task 1: Fit-width panel + collapse toggle

**Files:**
- Modify: `gerber2rml/gui/app.py` (settings_container min width; splitter sizes/
  collapsible; a `_panel_toggle` button on the machine bar; `_on_toggle_panel`)
- Test: `tests/test_window.py` (append)

**Interfaces:**
- Produces on `MainWindow`: `self._settings_container` (kept as an attribute),
  `self.panel_toggle` (checkable QPushButton), `_on_toggle_panel(checked)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_window.py
def test_settings_panel_fit_width_and_collapse():
    w = MainWindow()
    assert w._settings_container.minimumWidth() >= 520      # fits fields, no clip
    w._on_toggle_panel(True)                                # collapse
    assert not w._settings_container.isVisible()
    assert w.preview.isVisible()                            # preview never hidden
    w._on_toggle_panel(False)                               # restore
    assert w._settings_container.isVisible()
```

- [ ] **Step 2: Run it (expect fail)**

Run: `python -m pytest tests/test_window.py -k fit_width_and_collapse -q`
Expected: FAIL (`_settings_container` / `_on_toggle_panel` missing).

- [ ] **Step 3: Implement**

Replace the settings_container/splitter block:

```python
        self._settings_container = QWidget()
        sc_layout = QHBoxLayout(self._settings_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(0)
        sc_layout.addWidget(self.sidebar)
        sc_layout.addWidget(self.stacked_widget)
        self._settings_container.setMinimumWidth(520)   # sidebar 180 + fields ~340
```

(Use `self._settings_container` everywhere the old local `settings_container`
was referenced in the splitter block.)

```python
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._settings_container)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, True)      # panel may be hidden by the toggle
        splitter.setCollapsible(1, False)     # preview can never collapse
        splitter.setSizes([520, 10000])       # panel at fit-width, preview the rest
```

Add the toggle button to the machine bar (before `self.dro_label`):

```python
        self.panel_toggle = QPushButton("◀")
        self.panel_toggle.setCheckable(True)
        self.panel_toggle.setFixedWidth(28)
        self.panel_toggle.setToolTip("Hide / show the settings panel")
        self.panel_toggle.toggled.connect(self._on_toggle_panel)
        ...
        _mb.addWidget(self.panel_toggle)      # first widget on the bar
        _mb.addWidget(self.dro_label)
```

Add the handler (near other small UI handlers):

```python
    def _on_toggle_panel(self, collapsed):
        """Hide the settings panel for a full-width preview, or restore it."""
        self._settings_container.setVisible(not collapsed)
        self.panel_toggle.setText("▶" if collapsed else "◀")
```

- [ ] **Step 4: Run the test + the window suite**

Run: `python -m pytest tests/test_window.py -k fit_width_and_collapse -q` → PASS.
Then `python -m pytest tests/test_window.py -q` → green.

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui/app.py tests/test_window.py
git commit -m "feat(gui): fit-width settings panel + collapse toggle"
```

## Self-Review
- Spec: fit width (520) ✓, preview absorbs (stretch + non-collapsible) ✓, initial
  split ✓, collapse toggle ✓, test ✓. No placeholders; names consistent
  (`_settings_container`, `panel_toggle`, `_on_toggle_panel`).
