"""Notes list + composer, used on guests, reservations and rooms."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget)

from motelmg.ui.widgets.common import Badge, EmptyState, button, clear_layout, icon_button, label
from motelmg.ui.widgets.dialogs import confirm, guarded


class NotesPanel(QWidget):
    def __init__(self, app, *, guest_id: int | None = None, reservation_id: int | None = None,
                 room_id: int | None = None):
        super().__init__()
        self.setObjectName("Transparent")
        self.app = app
        self.target = {"guest_id": guest_id, "reservation_id": reservation_id, "room_id": room_id}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        composer = QFrame()
        composer.setProperty("soft", True)
        cl = QVBoxLayout(composer)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(8)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Add a note visible to all staff…")
        self.editor.setFixedHeight(64)
        self.editor.setTabChangesFocus(True)
        self.important = QCheckBox("Important (highlight at check-in)")
        add = button("Add note", "plus", "primary", small=True, on_click=self._add)
        row = QHBoxLayout()
        row.addWidget(self.important)
        row.addStretch(1)
        row.addWidget(add)
        cl.addWidget(self.editor)
        cl.addLayout(row)
        layout.addWidget(composer)
        self.list_host = QWidget()
        self.list_host.setObjectName("Transparent")
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.list_host)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll, 1)
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.list_layout)
        notes = self.app.ctx.notes.list(**self.target)
        if not notes:
            self.list_layout.addWidget(EmptyState("note", "No notes yet", "Notes help the next shift know what "
                                                  "happened.", compact=True))
        for note in notes:
            self.list_layout.addWidget(self._note_card(note))
        self.list_layout.addStretch(1)

    def _note_card(self, note) -> QFrame:
        card = QFrame()
        card.setProperty("card", True)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 9, 8, 10)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(label(note.author, "h3"))
        head.addWidget(label(self.app.fmt.datetime(note.created_at), "faint"))
        if note.is_important:
            head.addWidget(Badge("Important", "red", small=True))
        head.addStretch(1)
        session = self.app.ctx.session
        if session:
            head.addWidget(icon_button("trash", "Delete note", lambda n=note: self._delete(n), size=14))
        lay.addLayout(head)
        body = label(note.body, wrap=True, selectable=True)
        lay.addWidget(body)
        return card

    def _add(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            self.editor.setFocus()
            return
        if guarded(self, lambda: self.app.ctx.notes.add(text, important=self.important.isChecked(), **self.target)):
            self.editor.clear()
            self.important.setChecked(False)
            self.refresh()

    def _delete(self, note) -> None:
        if confirm(self, "Delete note", "Delete this note? This cannot be undone.", "Delete", danger=True):
            if guarded(self, lambda: self.app.ctx.notes.delete(note.id)):
                self.refresh()


__all__ = ["NotesPanel", "Qt"]
