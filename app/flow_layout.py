"""A layout that places items left to right and wraps them onto new lines.

Qt has no wrapping layout built in; this is the ``FlowLayout`` from Qt's own
examples, ported to PySide6. The option rows use it so a narrow window
(a tiling window manager giving the app half the screen, say) wraps the
checkboxes onto more lines instead of cutting them off or overlapping.

Implements ``heightForWidth`` so a containing layout — and the window's
scroll area — gets the wrapped height.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, h_spacing: int = 20,
                 v_spacing: int = 10) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    # --- QLayout API -----------------------------------------------------

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    # --- layout ----------------------------------------------------------

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        # Break the items into lines, then place each line with its items
        # centred vertically (a checkbox next to a taller button lines up).
        lines: list[list[tuple[QLayoutItem, QSize]]] = [[]]
        x = area.x()
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if lines[-1] and x + hint.width() > area.right() + 1:
                lines.append([])
                x = area.x()
            lines[-1].append((item, hint))
            x += hint.width() + self._h_spacing

        y = area.y()
        for index, line in enumerate(lines):
            if not line:
                continue
            line_height = max(hint.height() for _, hint in line)
            if not test_only:
                x = area.x()
                for item, hint in line:
                    offset = (line_height - hint.height()) // 2
                    item.setGeometry(QRect(QPoint(x, y + offset), hint))
                    x += hint.width() + self._h_spacing
            y += line_height + (self._v_spacing if index < len(lines) - 1 else 0)
        return y - rect.y() + margins.bottom()


def group(*widgets: QWidget, spacing: int = 6) -> QWidget:
    """Keep related widgets together on one line of a FlowLayout
    (a label and its field, a checkbox and its button)."""
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(spacing)
    for widget in widgets:
        row.addWidget(widget)
    return box
