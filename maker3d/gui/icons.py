"""Small line icons drawn from inline SVG so they stay sharp at any DPI."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "select": '<path d="M6 3l12 9-5.5 1 3.5 7-2.5 1.2-3.5-7L6 18z"/>',
    "line": '<path d="M4 18l6-10 5 6 5-9"/><circle cx="4" cy="18" r="1.6"/><circle cx="10" cy="8" r="1.6"/>'
            '<circle cx="15" cy="14" r="1.6"/><circle cx="20" cy="5" r="1.6"/>',
    "rect": '<rect x="4" y="6" width="16" height="12" rx="1"/>',
    "circle": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="1.2"/>',
    "shapes": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
    "text": '<path d="M5 6h14M12 6v13M9 19h6"/>',
    "more": '<circle cx="6" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="18" cy="12" r="1.5"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 010 10h-3"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9a5 5 0 000 10h3"/>',
    "export": '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M4 17v3h16v-3"/>',
    "new": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M12 11v6M9 14h6"/>',
    "open": '<path d="M3 7h6l2 2h10v10H3z"/>',
    "save": '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    "fit": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "view": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 3v9l8 4.5M12 12l-8 4.5"/>',
    "pull": '<path d="M12 20V5M7 10l5-5 5 5"/><path d="M5 20h14"/>',
    "hole": '<ellipse cx="12" cy="8" rx="7" ry="3"/><path d="M5 8v8c0 1.7 3.1 3 7 3s7-1.3 7-3V8"/>'
            '<path d="M12 11v6M9.5 14.5L12 17l2.5-2.5"/>',
    "fillet": '<path d="M4 20V10a6 6 0 016-6h10"/>',
    "chamfer": '<path d="M4 20V10l6-6h10"/>',
    "shell": '<path d="M4 8l8-4 8 4v9l-8 4-8-4z"/><path d="M7 9.5l5-2.5 5 2.5v6l-5 2.5-5-2.5z"/>',
    "mirror": '<path d="M12 3v18" stroke-dasharray="2 2"/><path d="M9 7L4 17h5zM15 7l5 10h-5z"/>',
    "scale": '<path d="M4 20l16-16M14 4h6v6M10 20H4v-6"/>',
    "trash": '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>',
    "look": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "import": '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v3h16v-3"/>',
    "history": '<path d="M4 12a8 8 0 108-8 8 8 0 00-6 2.7"/><path d="M4 4v4h4M12 8v4l3 2"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 015 .5c0 1.7-2.5 2-2.5 4M12 17h.01"/>',
}


@lru_cache(maxsize=None)
def icon(name: str, color: str = "#2b3440", size: int = 48) -> QIcon:
    body = _P.get(name, _P["more"])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    ic = QIcon(pm)
    # white version for checked/active state
    if color != "#ffffff":
        white = icon(name, "#ffffff", size).pixmap(size, size)
        ic.addPixmap(white, QIcon.Normal, QIcon.On)
    return ic
