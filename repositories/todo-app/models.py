"""In-memory todo storage for the Flask Todo demo application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class TodoNotFound(KeyError):
    pass


@dataclass
class Todo:
    id: int
    title: str
    done: bool = False

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "done": self.done}


class TodoStore:
    def __init__(self) -> None:
        self._items: dict[int, Todo] = {}
        self._next_id = 1

    def list(self) -> list[Todo]:
        return list(self._items.values())

    def get(self, todo_id: int) -> Todo:
        if todo_id not in self._items:
            raise TodoNotFound(todo_id)
        return self._items[todo_id]

    def create(self, title: str, due_date: Optional[str] = None) -> Todo:
        todo = Todo(id=self._next_id, title=title)
        self._items[todo.id] = todo
        self._next_id += 1
        return todo

    def update(self, todo_id: int, **fields) -> Todo:
        todo = self.get(todo_id)
        for key, value in fields.items():
            if value is not None and hasattr(todo, key):
                setattr(todo, key, value)
        return todo

    def delete(self, todo_id: int) -> None:
        self.get(todo_id)
        del self._items[todo_id]
