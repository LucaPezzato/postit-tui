"""Custom UI widgets for postit-tui."""

from __future__ import annotations

import re

from textual import events
from textual.widgets import TextArea

CHECKBOX_ITEM_RE = re.compile(r"^(\s*)(?:([-*•])\s+)?\[([ xX])\](\s*)(.*)$")
BULLET_ITEM_RE = re.compile(r"^(\s*)([-*•])(\s+)(.*)$")


class ChecklistTextArea(TextArea):
    """A TextArea that automatically continues checklist items (- [ ]) when pressing Enter."""

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter" and not self.read_only:
            start, end = self.selection
            # Only intercept if there is no active multi-character selection
            if start == end:
                row, col = self.cursor_location
                line = self.document.get_line(row)

                # 1. Existing checklist item: - [ ] Task, - [x] Task, etc.
                m_cb = CHECKBOX_ITEM_RE.match(line)
                if m_cb:
                    indent, bullet, mark, space_after, rest = m_cb.groups()
                    if not rest.strip():
                        # Empty checkbox item: pressing Enter clears the marker to easily exit the list
                        event.stop()
                        event.prevent_default()
                        self.replace("", (row, 0), (row, len(line)), maintain_selection_offset=False)
                        return

                    text_start = len(line) - len(rest)
                    if col >= text_start:
                        event.stop()
                        event.prevent_default()
                        new_prefix = f"\n{indent}- [ ] "
                        self.replace(new_prefix, (row, col), (row, col), maintain_selection_offset=False)
                        return

                # 2. Plain bullet item: - Task, * Task, etc. (auto-upgrades to - [ ])
                m_b = BULLET_ITEM_RE.match(line)
                if m_b:
                    indent, bullet, space_after, rest = m_b.groups()
                    if not rest.strip():
                        # Empty bullet item: pressing Enter clears the line
                        event.stop()
                        event.prevent_default()
                        self.replace("", (row, 0), (row, len(line)), maintain_selection_offset=False)
                        return

                    text_start = len(line) - len(rest)
                    if col >= text_start:
                        event.stop()
                        event.prevent_default()
                        before_cursor = line[text_start:col]
                        after_cursor = line[col:]
                        new_current_line = f"{indent}- [ ] {before_cursor}"
                        new_next_line = f"{indent}- [ ] {after_cursor}"
                        replacement = f"{new_current_line}\n{new_next_line}"
                        self.replace(replacement, (row, 0), (row, len(line)), maintain_selection_offset=False)
                        self.cursor_location = (row + 1, len(indent) + 6)
                        return

        await super()._on_key(event)
