"""In-memory blog storage for the Blog demo application."""

from __future__ import annotations

from dataclasses import dataclass


class NotFound(KeyError):
    pass


@dataclass
class Post:
    id: int
    title: str
    author: str
    body: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "author": self.author, "body": self.body}


@dataclass
class Comment:
    id: int
    post_id: int
    author: str
    body: str

    def to_dict(self) -> dict:
        return {"id": self.id, "post_id": self.post_id, "author": self.author, "body": self.body}


class BlogStore:
    def __init__(self) -> None:
        self._posts: dict[int, Post] = {}
        self._comments: dict[int, Comment] = {}
        self._next_post_id = 1
        self._next_comment_id = 1

    # -- posts -------------------------------------------------------------
    def list_posts(self) -> list[Post]:
        return list(self._posts.values())

    def get_post(self, post_id: int) -> Post:
        if post_id not in self._posts:
            raise NotFound(post_id)
        return self._posts[post_id]

    def create_post(self, title: str, author: str, body: str = "") -> Post:
        post = Post(id=self._next_post_id, title=title, author=author, body=body)
        self._posts[post.id] = post
        self._next_post_id += 1
        return post

    def delete_post(self, post_id: int) -> None:
        self.get_post(post_id)
        del self._posts[post_id]

    # -- comments ----------------------------------------------------------
    def list_comments(self, post_id: int) -> list[Comment]:
        return [c for c in self._comments.values() if c.post_id == post_id]

    def add_comment(self, post_id: int, author: str, body: str) -> Comment:
        self.get_post(post_id)
        comment = Comment(
            id=self._next_comment_id, post_id=post_id, author=author, body=body
        )
        self._comments[comment.id] = comment
        self._next_comment_id += 1
        return comment
