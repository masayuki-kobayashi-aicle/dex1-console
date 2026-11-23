"""Human interaction behind one small interface, so the preflight and console can be tested with scripted input."""
from __future__ import annotations

from typing import Protocol


class Prompter(Protocol):
    def say(self, msg: str) -> None: ...
    def ask(self, prompt: str) -> str: ...  # one line typed by the person


class TerminalPrompter:
    def say(self, msg: str) -> None:
        print(msg, flush=True)

    def ask(self, prompt: str) -> str:
        return input(prompt)


class ScriptedPrompter:
    """Answers from a list; records what was said. For tests."""

    def __init__(self, answers: list[str]) -> None:
        self.answers, self.said = list(answers), []

    def say(self, msg: str) -> None:
        self.said.append(msg)

    def ask(self, prompt: str) -> str:
        self.said.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)
