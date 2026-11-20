---
name: cad-ux
description: UX/UI rules for the 3D Maker desktop CAD app (PySide6 + PyVista + build123d), modelled on Shapr3D. Use whenever changing anything the user sees or touches in maker3d/gui — viewport mouse/keyboard/pen input, selection and hover, sketch drawing, drag-to-pull, the context (command) bar, hint text, theme, icons or Thai wording — and before saying a UI change works.
---

# 3D Maker UX rules

3D Maker is a Thai-language CAD app for people who 3D print, built to feel like Shapr3D on a
Windows PC with a mouse (or a pen on a Windows tablet). The users are new to CAD. Every UI
change must keep these rules and must be tested with real Qt input before it is called done.

## Interaction model: select first, then act

- Hover shows what a click would pick (light blue). A click selects it (cobalt). Shift/Ctrl+click
  adds or removes. One kind of thing is selected at a time: faces, edges, or sketch profiles.
- The dark command bar under the viewport (`contextBar`) shows only actions that apply to the
  current selection. Nothing selected → it offers ways to start (draw rectangle, draw circle, box).
- The coach line above the viewport (`hintBar`) always says the next step in one sentence, in
  plain Thai, with keys shown as chips. Update `HINTS` in `viewport.py` when behaviour changes.
- A drawn shape is auto-selected and the tool returns to Select, so the next move is to drag the
  arrow. A pullable selection always shows the blue arrow; dragging it previews in green (add) or
  red (cut) with the distance next to the cursor, and commits on release.
- Every action is undoable (`Document.checkpoint()` before any change) and shows up in history.

## Mouse, keyboard, pen (Shapr3D on Windows defaults)

| Input | Action |
|---|---|
| Left click | select / place sketch point / press arrow |
| Left drag on empty space | orbit |
| Right drag | orbit (turntable: Z stays up, never roll, never flip over the top) |
| Right click without moving | cancel / Esc |
| Middle drag, Shift+right drag | pan |
| Wheel | zoom towards the cursor |
| Double click (line tool) | close the polygon |
| V L R C | Select, Line, Rectangle, Circle · Esc cancels · typing digits while drawing sets size |

- All pointer input is handled in Qt (`mousePressEvent` etc. in `Viewport`). VTK gets no mouse
  events and its interactor style is `vtkInteractorStyleUser`. Never route input through VTK
  observers again: pyvista can swap the style and input then silently dies.
- Convert Qt logical coords to VTK display pixels with `Viewport._xy()` (ratio of render-window
  size to widget size) — never assume devicePixelRatio is 1. Scale pixel tolerances by `_scale`.
- `QtInteractor` already defines `.mesh`; never name viewport attributes after pyvista Plotter API.
- Drag distances along an axis use the closest point between the mouse ray and the 3D axis
  (`_line_param`), not screen-space projection (perspective makes that wrong).
- Pen on Windows arrives as mouse events (tip = left, barrel button = right). Keep every gesture
  reachable with those two plus the keyboard.

## Drawing on faces

- The sketch plane is the planar face under the first click, otherwise the print bed (Z=0).
- Snap order: point snaps (face centre, corners, edge midpoints, hole centres, coplanar sketch
  points; within 12 px, marker turns green) → grid (`snap`, default 1 mm) → Shift = 0.1 mm free.
- Typed sizes: circle = diameter, rectangle = `w,h`. Show live size next to the cursor.
  VTK text has no Thai glyphs: labels drawn in the viewport must be ASCII (numbers, mm, D, x).

## Visual design

Tokens live in `maker3d/gui/theme.py`; do not hard-code new colours elsewhere.

- Light studio canvas (`#eef2f6`→`#cdd6e0`), white panels, ink `#17202b`.
- Cobalt `#1f5bff` = selection and the single primary action per bar. Amber `#f2a81d` = sketches.
  Green `#1e9e5a` = add, red `#de4a3c` = cut. Don't reuse these for anything else.
- The dark command bar is the one bold element. Keep everything else quiet: no gradients on
  panels, no extra shadows, no decorative labels.
- Font: bundled IBM Plex Sans Thai (`maker3d/gui/fonts`, OFL). Sentence case, active verbs.
  A button says what happens ("เจาะทะลุ", "ดึงขึ้น"); the history item uses the same word.
- Errors say what failed and what to try ("ลองลดค่ารัศมี…"), shown on the history item in red
  and in the properties panel. Unhandled exceptions go to `~/.3dmaker/3dmaker.log` and a dialog.

## Definition of done for any UI change

1. `python -m pytest -q` passes.
2. `xvfb-run -a python tools/ui_e2e.py` prints `RESULT: ALL PASS`, and
   `QT_SCALE_FACTOR=1.5 xvfb-run -a python tools/ui_e2e.py` too (simulates 150% Windows scaling).
   These drive the app with real `QMouseEvent`/`QWheelEvent`/`QTest` key events only. Extend the
   script for any new interaction — never test by calling VTK events or private handlers directly.
3. Look at the screenshots it writes (`build/ui-shots`) and fix anything cramped, clipped or
   unreadable at 1440×900 before reporting.
4. Say plainly what was only tested on Linux/xvfb and what still needs a check on real Windows.

Related skills in this repo: `frontend-design` (visual direction), `web-design-guidelines`
(review checklist — apply the parts that translate to Qt: focus states, keyboard alternatives,
hover/active contrast, error copy, destructive actions need undo).
