"""In-memory user and session storage for the auth-service demo application."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    id: int
    username: str
    password: str

    def to_dict(self) -> dict:
        return {"id": self.id, "username": self.username}


@dataclass
class Session:
    token: str
    user_id: int
    created_at: float
    expires_at: float


class AuthStore:
    def __init__(self) -> None:
        self.users: dict[int, User] = {}
        self.sessions: dict[str, Session] = {}
        self._next_id = 1

    def register(self, username: str, password: str) -> User:
        user = User(id=self._next_id, username=username, password=password)
        self.users[user.id] = user
        self._next_id += 1
        return user

    def find_by_username(self, username: str) -> Optional[User]:
        for user in self.users.values():
            if user.username == username:
                return user
        return None

    def authenticate(self, username: str, password: str) -> Optional[User]:
        user = self.find_by_username(username)
        if user is None or user.password != password:
            return None
        return user

    def create_session(self, user_id: int, ttl: Optional[float] = None) -> Session:
        session = Session(
            token=secrets.token_hex(16),
            user_id=user_id,
            created_at=time.time(),
            expires_at=0.0,
        )
        self.sessions[session.token] = session
        return session

    def get_session(self, token: str) -> Optional[int]:
        session = self.sessions.get(token)
        if session is None:
            return None
        return session.user_id

    def delete_session(self, token: str) -> None:
        self.sessions.pop(token, None)
