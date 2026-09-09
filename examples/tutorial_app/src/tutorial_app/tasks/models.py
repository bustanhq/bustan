"""The shapes a task takes on the way in and on the way out."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


class CreateTaskPayload(BaseModel):
    """What a caller sends to create a task.

    A Pydantic model on a handler parameter is validated before the handler runs, so a
    bad request never reaches this application's code and answers with a problem
    document naming the field.
    """

    title: str = Field(min_length=1, max_length=120)
    done: bool = False


@dataclass(frozen=True, slots=True)
class Task:
    """A task as it is stored and returned."""

    id: int
    title: str
    done: bool
