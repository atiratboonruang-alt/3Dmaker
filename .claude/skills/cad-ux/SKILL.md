---
name: cad-ux
description: UX/UI rules for the 3D Maker desktop CAD app (PySide6 + PyVista + build123d), a direct-modelling app in the style of Shapr3D. Use whenever changing anything the user sees or touches in maker3d/gui — viewport mouse/keyboard/pen input, Modeling/Sketching modes, selection and hover, sketch tools and snapping, drag-to-extrude, the tool panel, command bar, instruction text, theme, icons or wording — and before saying a UI change works.
---

# 3D Maker UX rules

3D Maker is a CAD app for people who 3D print, built to feel like Shapr3D on a Windows PC with
a mouse (or a pen on a Windows tablet). The owner is Thai but wants **all UI text in English**
(talk to them in Thai). Users are new to CAD. Every UI change must keep these rules and must be
tested with real Qt input before it is called done. Follow the workflow, not the branding: draw
our own icons, never copy another app's logo, artwork or name.

## Two modes

- **Modeling**: select faces, edges and sketch regions; drag the arrow to extrude/cut. Left
  panel: Sketch (K), Insert ▸, Tools ▸, Select, Fit View, Quick Guide.
- **Sketching**: entered by double-clicking a planar face (or the bed / a region), by the Sketch
  item, or by a sketch tool key then clicking a plane. The camera animates (~300 ms, time-based)
  to look straight at the plane, switches to orthographic, and a grid + red (u) / blue (v) axes
  appear. Left panel: Exit Sketching (Esc), Select (V), Line (L), Rectangle (R), Circle (C),
  Polygon (G), Slot (S), Delete. Tools stay active after each shape. Esc cancels the last line
  segment → leaves the tool → exits sketching. Double-click another face to move there; double-click
  empty space to exit. On exit, the closed regions you just drew are selected, so the next move
  is dragging the arrow.

## Interaction model: select first, then act

- Hover shows what a click would pick (light blue). A click selects it (cobalt). Shift/Ctrl+click
  adds or removes. One kind of thing is selected at a time: faces, edges, or sketch profiles.
- The dark command bar under the viewport (`contextBar`) shows only actions that apply to the
  current selection. Nothing selected → it offers ways to start (draw rectangle, draw circle, box).
- The instruction box centred above the viewport (`hintBar`) always says the next step, in plain
  English sentence case, with keys as chips (“Place the line's endpoints. To finish, press Enter.”).
  Update `HINTS` in `viewport.py` when behaviour changes.
- Selected edges show a round handle on the last edge, pointing out along the bisector of its two
  faces. Dragging it previews the fillet live (`R 2.0 mm`, 0.5 mm steps, Shift 0.1 mm; red label
  when too large, last valid radius is kept) and commits a Fillet on release.
- A pullable selection always shows the blue arrow; dragging it previews in green (add) or red
  (cut) with the distance next to the cursor, and commits on release. A plain click (no drag) on
  one of several selected items selects just that one.
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
| V L R C G S K | Select, Line, Rectangle, Circle, Polygon, Slot, Sketch · Esc back · typing digits while drawing sets the size |

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

## Snapping while sketching (`Viewport._snap`)

1. Points within 12 px: plane origin, face centre, model corners/edge midpoints/hole centres on
   the plane, vertices/midpoints/centres of coplanar sketch shapes, the line chain's own points
   (clicking the start point closes the loop). Marker: purple.
2. Horizontal/vertical alignment with those points within 8 px: blue guide line from the point.
3. Onto lines within 8 px: model edges in the plane and sketch outlines. Marker: blue.
4. Grid: step follows zoom (≥14 px per cell, 1-2-5 series) unless Snap is set in the status bar.
5. Shift = free placement at 0.1 mm.
All pixel tolerances are logical pixels: multiply by `_scale` (and `pixel_size()` by `_scale` to
get mm per logical pixel) — dividing broke snapping at 150 % Windows scaling once.

- Typed sizes: line = length along the cursor direction, circle = diameter, rectangle = `w,h`,
  polygon = radius, slot = length then width. The live dimension box (`_place_label`) stays inside
  the viewport. VTK text has no Thai glyphs: viewport labels must be ASCII.

## Visual design

Tokens live in `maker3d/gui/theme.py` (Qt) and the top of `viewport.py` (3D colours); do not
hard-code new colours elsewhere.

- Dark studio: window `#1b1c1f`, panels `#232428`, raised controls `#2c2e33`, text `#e8e9ec`.
  The part is light grey `#c9ccd1` so it carries the scene.
- Cobalt `#3d8bff` = selection, the primary action per bar and the v axis. Amber `#ffb02e` =
  sketches. Purple `#b07cff` = sketch vertices and point snaps. Green = add, red = cut / u axis.
- Tool panel rows: square icon button, bold name, shortcut chip, grey sub-label (e.g. “Hexagon”).
- Font: bundled IBM Plex Sans Thai (`maker3d/gui/fonts`, OFL; Latin + Thai). Sentence case,
  active verbs. A button says what happens (“Cut Through”, “Extrude”); the history item uses the
  same word.
- Errors say what failed and what to try (“Try a smaller radius…”), shown on the history item in
  red and in the properties panel. Unhandled exceptions go to `~/.3dmaker/3dmaker.log` + a dialog.

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
