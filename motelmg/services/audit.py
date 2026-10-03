from __future__ import annotations

import json
from datetime import date
from typing import Any

from motelmg.models import AuditEntry


class AuditService:
    """Append-only trail of important actions, attributed to the signed-in user."""

    def __init__(self, ctx):
        self.ctx = ctx

    def log(self, action: str, entity_type: str, entity_id: int | None, summary: str,
            details: dict[str, Any] | None = None) -> None:
        session = self.ctx.session
        payload = json.dumps(details, default=str, sort_keys=True) if details else ""
        self.ctx.repo_audit.insert(
            self.ctx.now_str(), session.user_id if session else None,
            session.username if session else "system", action, entity_type, entity_id, summary, payload)

    def search(self, *, start: date | None = None, end: date | None = None, user_id: int | None = None,
               action_prefix: str = "", text: str = "", entity_type: str = "", entity_id: int | None = None,
               limit: int = 2000) -> list[AuditEntry]:
        self.ctx.require("audit.view")
        return self.ctx.repo_audit.search(start=start, end=end, user_id=user_id, action_prefix=action_prefix,
                                          text=text, entity_type=entity_type, entity_id=entity_id, limit=limit)

    def for_entity(self, entity_type: str, entity_id: int) -> list[AuditEntry]:
        """History of one record - visible to anyone who can see the record."""
        return self.ctx.repo_audit.search(entity_type=entity_type, entity_id=entity_id, limit=500)

    def action_groups(self) -> list[str]:
        return sorted({a.split(".")[0] for a in self.ctx.repo_audit.actions()})
