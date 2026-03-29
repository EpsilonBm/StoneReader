"""Left navigation sidebar widgets."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem


class Sidebar(QTreeWidget):
    """Shows shelf scopes and tag nodes."""

    scopeChanged = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderHidden(True)
        self.setMinimumWidth(220)
        self.itemClicked.connect(self._emit_scope)

        self.shelf_item = QTreeWidgetItem(["书架"])
        self.tags_item = QTreeWidgetItem(["标签"])
        self.favorite_item = QTreeWidgetItem(["最爱"])
        self.read_item = QTreeWidgetItem(["已读"])

        self.addTopLevelItems([self.shelf_item, self.tags_item, self.favorite_item, self.read_item])
        self.expandAll()

    def set_tags(self, tags: list[str]) -> None:
        self.tags_item.takeChildren()
        for tag in tags:
            self.tags_item.addChild(QTreeWidgetItem([tag]))
        self.expandItem(self.tags_item)

    def _emit_scope(self, item: QTreeWidgetItem) -> None:
        if item is self.shelf_item:
            self.scopeChanged.emit("shelf", "")
        elif item is self.favorite_item:
            self.scopeChanged.emit("favorites", "")
        elif item is self.read_item:
            self.scopeChanged.emit("read", "")
        elif item.parent() is self.tags_item:
            self.scopeChanged.emit("tag", item.text(0))
