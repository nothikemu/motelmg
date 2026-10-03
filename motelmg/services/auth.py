"""Authentication: password hashing, sign-in with lockout, password changes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from datetime import timedelta

from motelmg.core.dates import parse_datetime
from motelmg.core.errors import AuthenticationError, ValidationError
from motelmg.services.context import Session

PBKDF2_ITERATIONS = 200_000
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 5
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str, *, username: str = "", field: str = "password") -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.", field=field)
    if len(password) > 128:
        raise ValidationError("Password is too long (maximum 128 characters).", field=field)
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValidationError("Password must contain both letters and numbers.", field=field)
    if username and password.lower() == username.lower():
        raise ValidationError("Password cannot be the same as the username.", field=field)


class AuthService:
    def __init__(self, ctx):
        self.ctx = ctx

    def has_users(self) -> bool:
        return self.ctx.repo_staff.user_count() > 0

    def login(self, username: str, password: str) -> Session:
        username = (username or "").strip()
        if not username or not password:
            raise AuthenticationError("Enter your username and password.")
        repo = self.ctx.repo_staff
        row = repo.get_user_row(username)
        now = self.ctx.clock.now()
        generic = "Incorrect username or password."
        if row is None:
            # Spend comparable time to avoid revealing which usernames exist.
            verify_password(password, hash_password("x", iterations=1000))
            raise AuthenticationError(generic)
        if not row["is_active"]:
            raise AuthenticationError("This account has been deactivated. Contact your administrator.")
        locked_until = parse_datetime(row["locked_until"])
        if locked_until and locked_until > now:
            minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
            raise AuthenticationError(
                f"Too many failed attempts. The account is locked for {minutes} more minute(s).")
        if not verify_password(password, row["password_hash"]):
            attempts = int(row["failed_attempts"]) + 1
            values: dict = {"failed_attempts": attempts}
            message = generic
            if attempts >= MAX_FAILED_ATTEMPTS:
                values["locked_until"] = (now + timedelta(minutes=LOCKOUT_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
                values["failed_attempts"] = 0
                message = f"Too many failed attempts. The account is locked for {LOCKOUT_MINUTES} minutes."
            with self.ctx.db.transaction():
                repo.update_user(row["id"], values)
                self.ctx.repo_audit.insert(self.ctx.now_str(), row["id"], row["username"], "auth.login_failed",
                                           "user", row["id"], f"Failed sign-in for {row['username']}", "")
            raise AuthenticationError(message)
        with self.ctx.db.transaction():
            repo.update_user(row["id"], {"failed_attempts": 0, "locked_until": None,
                                         "last_login_at": self.ctx.now_str()})
            session = self._session_for(row["id"])
            self.ctx.session = session
            self.ctx.audit.log("auth.login", "user", row["id"], f"{session.full_name} signed in")
        return session

    def _session_for(self, user_id: int) -> Session:
        user = self.ctx.repo_staff.get_user(user_id)
        assert user is not None
        perms = self.ctx.repo_staff.permissions(user.role_id)
        return Session(user_id=user.id, username=user.username, full_name=user.full_name, role_id=user.role_id,
                       role_name=user.role_name, permissions=perms, must_change_password=user.must_change_password)

    def refresh_session(self) -> None:
        """Reload role permissions after an administrator changed them."""
        if self.ctx.session:
            user = self.ctx.repo_staff.get_user(self.ctx.session.user_id)
            if user and user.is_active:
                self.ctx.session = self._session_for(user.id)

    def logout(self) -> None:
        if self.ctx.session:
            with self.ctx.db.transaction():
                self.ctx.audit.log("auth.logout", "user", self.ctx.session.user_id,
                                   f"{self.ctx.session.full_name} signed out")
        self.ctx.session = None

    def verify_current_user(self, password: str) -> bool:
        if not self.ctx.session:
            return False
        return verify_password(password, self.ctx.repo_staff.password_hash(self.ctx.session.user_id))

    def change_password(self, current: str, new: str, confirm: str) -> None:
        session = self.ctx.session
        if session is None:
            raise AuthenticationError("You must be signed in.")
        if not self.verify_current_user(current):
            raise ValidationError("Current password is incorrect.", field="current")
        if new != confirm:
            raise ValidationError("The new passwords do not match.", field="confirm")
        if new == current:
            raise ValidationError("The new password must be different from the current one.", field="new")
        validate_password_strength(new, username=session.username, field="new")
        with self.ctx.db.transaction():
            self.ctx.repo_staff.update_user(session.user_id, {
                "password_hash": hash_password(new), "must_change_password": 0,
                "password_changed_at": self.ctx.now_str(), "updated_at": self.ctx.now_str()})
            self.ctx.audit.log("auth.password_changed", "user", session.user_id,
                               f"{session.full_name} changed their password")
        session.must_change_password = False
