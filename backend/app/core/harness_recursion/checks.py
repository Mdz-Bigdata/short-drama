"""The ``scripts`` component: checks of an output that a machine can run, declared and never executed as code.

Harness² lets a proposer add scripts for "repeated deterministic extraction, conversion or checking"
and asks that the deliverable be mechanically checked before it is handed on. Its agent runs those
scripts in its tool loop. A stage agent here makes one model call and runs nothing, and a script a
model wrote is not something this server will execute, so the component is a short list of checks in
a fixed grammar. The engine runs them on every execution of the stage call (the result is evidence
for the improvers, as a script's output is upstream), and the agent reads the same list in words.

    max_chars: 5000          min_chars: 800
    include: 三幕大纲         exclude: 已确认
    min_count: 钩子 | 3       max_count: 待定 | 2
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.harness_recursion import prompts

KINDS: tuple[str, ...] = tuple(prompts.table("checks")["kinds"])
_SIZED = ("max_chars", "min_chars")
_COUNTED = ("min_count", "max_count")


class CheckError(ValueError):
    """A line that is not a check; the message goes back to whoever wrote it."""


@dataclass(frozen=True)
class Check:
    kind: str
    text: str = ""
    n: int = 0

    def says(self) -> str:
        """The check as the agent reads it."""
        return str(prompts.table("checks")["says"][self.kind]).format(text=self.text, n=self.n)

    def failure(self, output: str) -> str | None:
        """What is wrong with ``output`` by this check, or None when it passes."""
        actual = len(output) if self.kind in _SIZED else output.count(self.text)
        failed = {
            "max_chars": actual > self.n, "min_chars": actual < self.n, "include": actual == 0, "exclude": actual > 0,
            "min_count": actual < self.n, "max_count": actual > self.n,
        }[self.kind]
        return str(prompts.table("checks")["failed"][self.kind]).format(text=self.text, n=self.n, actual=actual) if failed else None


def _number(value: str) -> int:
    digits = value.strip().replace(",", "").replace("，", "")
    if not digits.isdigit():
        raise ValueError(value)
    return int(digits)


def parse(script: str) -> list[Check]:
    """The checks a ``scripts`` component declares; raises ``CheckError`` naming every line it cannot read."""
    found: list[Check] = []
    problems: list[str] = []
    text_limit = prompts.limit("check_text_chars")
    for raw in str(script or "").splitlines():
        line = raw.strip().lstrip("-•* ").strip()
        if not line:
            continue
        kind, colon, value = line.replace("：", ":", 1).partition(":")
        kind, value = kind.strip().lower(), value.strip()
        try:
            if not colon or kind not in KINDS or not value:
                raise ValueError(line)
            if kind in _SIZED:
                check = Check(kind, n=_number(value))
            elif kind in _COUNTED:
                text, bar, count = value.replace("｜", "|").rpartition("|")
                if not bar or not text.strip():
                    raise ValueError(line)
                check = Check(kind, text=text.strip(), n=_number(count))
            else:
                check = Check(kind, text=value)
        except ValueError:
            problems.append(prompts.says("errors", "script_line", line=line[:80], kinds="、".join(KINDS)))
            continue
        if len(check.text) > text_limit:
            problems.append(prompts.says("errors", "script_text", size=len(check.text), limit=text_limit, text=check.text[:60]))
            continue
        found.append(check)
    if len(found) > prompts.limit("script_lines"):
        problems.append(prompts.says("errors", "script_lines", size=len(found), limit=prompts.limit("script_lines")))
    if problems:
        raise CheckError("\n".join(problems))
    return found


def readable(script: str) -> str:
    """The list in words, one check a line; empty for a component that declares nothing readable."""
    try:
        return "\n".join(f"- {check.says()}" for check in parse(script))
    except CheckError:
        return ""


def report(script: str, output: str) -> str:
    """What running the list on ``output`` found, as one observation; empty when there is no list."""
    try:
        declared = parse(script)
    except CheckError:
        return ""
    if not declared:
        return ""
    failures = [failure for check in declared if (failure := check.failure(output)) is not None]
    if not failures:
        return str(prompts.table("checks")["report_ok"]).format(total=len(declared))
    return str(prompts.table("checks")["report"]).format(total=len(declared), failed=len(failures), issues="；".join(failures))


__all__ = ["Check", "CheckError", "KINDS", "parse", "readable", "report"]
