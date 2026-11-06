# -*- coding: utf-8 -*-
"""An interactive story as plain data: the graph, its rules, and everything that can be proved about it.

A story is segments joined by two kinds of edge. A *choice* is picked by the viewer and may apply
effects; a *route* is followed by itself, first match wins, and is how an ending comes to depend on
what the viewer did. Conditions are data (``{var, op, value}`` under ``all`` / ``any``) so nothing a
person or a model typed is ever run as code.

Nothing here calls a model, touches the task store or reads a file. Three evaluators must agree on
what a condition means, this one, ``features/interactive/storyEngine.ts`` and the exported player's
``PLAYER_ENGINE_JS``; the tests run the same table through all three.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import random
import re
from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_serializer,
    model_validator,
)

MAX_SEGMENTS = 300
MAX_CHOICES_PER_SEGMENT = 8
MAX_ROUTES_PER_SEGMENT = 8
MAX_VARIABLES = 60
MAX_EFFECTS_PER_CHOICE = 12
MAX_CONDITION_DEPTH = 4
MAX_CONDITION_NODES = 24
MAX_DIALOGUE_LINES = 40
MAX_GRAPH_JSON_BYTES = 2 * 1024 * 1024
VALUE_LIMIT = 1e9

# JS code reads these ids as map keys; refusing them keeps a stray `constructor` from meaning something.
_RESERVED_IDS = {"__proto__", "constructor", "prototype", "hasOwnProperty", "toString", "valueOf"}
_ID_FORBIDDEN = re.compile(r"[\s<>\"'&\\`\x00-\x1f]")

Op = Literal["eq", "ne", "gt", "gte", "lt", "lte"]


class StoryInputError(ValueError):
    """The story as sent cannot be stored; the message says which part and why."""


def _check_id(value: str) -> str:
    if _ID_FORBIDDEN.search(value):
        raise ValueError("编号不能包含空白、引号或尖括号")
    if value in _RESERVED_IDS:
        raise ValueError(f"编号不能使用保留字 {value}")
    return value


def _finite(value: float) -> float:
    if not math.isfinite(value) or abs(value) > VALUE_LIMIT:
        raise ValueError(f"数值必须是绝对值不超过 {VALUE_LIMIT:g} 的有限数")
    return value


StoryId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64), AfterValidator(_check_id)]
Number = Annotated[Union[int, float], AfterValidator(_finite)]
# bool first: pydantic's smart union keeps the exact JSON type, so `true` never turns into 1.
Scalar = Union[bool, Number]


def _text(limit: int) -> Any:
    return Field(default="", max_length=limit)


class Condition(BaseModel):
    """Exactly one of: ``all``, ``any``, or a ``var`` / ``op`` / ``value`` comparison."""

    model_config = ConfigDict(extra="forbid")

    all: list["Condition"] | None = None
    any: list["Condition"] | None = None
    var: StoryId | None = None
    op: Op | None = None
    value: Scalar | None = None

    @model_validator(mode="after")
    def _one_form(self) -> "Condition":
        groups = (self.all is not None) + (self.any is not None)
        leaf = self.var is not None or self.op is not None or self.value is not None
        if groups > 1 or (groups and leaf):
            raise ValueError("一个条件只能是 all、any 或 var/op/value 之一")
        if not groups and (self.var is None or self.op is None or self.value is None):
            raise ValueError("比较条件必须同时给出 var、op、value")
        return self

    @model_serializer(mode="plain")
    def _dump(self) -> dict[str, Any]:
        if self.all is not None:
            return {"all": [item._dump() for item in self.all]}
        if self.any is not None:
            return {"any": [item._dump() for item in self.any]}
        return {"var": self.var, "op": self.op, "value": self.value}


class StoryVariable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StoryId
    label: str = _text(40)
    kind: Literal["number", "flag"] = "number"
    initial: Scalar | None = None
    min: Number | None = None
    max: Number | None = None

    @model_validator(mode="after")
    def _shape(self) -> "StoryVariable":
        if self.kind == "flag":
            if self.initial is None:
                self.initial = False
            if not isinstance(self.initial, bool):
                raise ValueError(f"标记变量 {self.id} 的初始值只能是 true 或 false")
            if self.min is not None or self.max is not None:
                raise ValueError(f"标记变量 {self.id} 不能设上下限")
            return self
        if self.initial is None:
            self.initial = 0
        if isinstance(self.initial, bool):
            raise ValueError(f"数值变量 {self.id} 的初始值不能是 true 或 false")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"变量 {self.id} 的下限大于上限")
        return self


class Effect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    var: StoryId
    op: Literal["add", "set"]
    value: Scalar


class StoryChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", max_length=80)
    text: str = _text(200)
    target: str | None = Field(default=None, max_length=64)
    condition: Condition | None = None
    # A gated choice is either kept out of sight or shown greyed out with a hint.
    when_locked: Literal["hide", "lock"] = "lock"
    locked_hint: str = _text(120)
    effects: list[Effect] = Field(default_factory=list, max_length=MAX_EFFECTS_PER_CHOICE)


class StoryRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default="", max_length=80)
    condition: Condition | None = None
    target: str | None = Field(default=None, max_length=64)


class StoryTimer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seconds: int = Field(ge=1, le=120)
    default_choice: str = Field(default="", max_length=80)


class StoryMedia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["video", "image"]
    url: str = Field(min_length=1, max_length=2048, pattern=r"^(https?://|/)[^\s\x00-\x1f<>\"'`\\]*$")
    source: Literal["shot", "clip", "episode", "upload"] = "upload"
    shot_uid: int | None = None
    label: str = _text(120)
    duration_s: float = Field(default=0.0, ge=0, le=7200, allow_inf_nan=False)


class DialogueLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: str = _text(60)
    text: str = _text(1000)


class StoryPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=-1e6, le=1e6, allow_inf_nan=False)
    y: float = Field(ge=-1e6, le=1e6, allow_inf_nan=False)


class StorySegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StoryId
    title: str = _text(120)
    kind: Literal["scene", "ending"] = "scene"
    narration: str = _text(4000)
    dialogue: list[DialogueLine] = Field(default_factory=list, max_length=MAX_DIALOGUE_LINES)
    media: StoryMedia | None = None
    est_seconds: float | None = Field(default=None, ge=0, le=7200, allow_inf_nan=False)
    ending_label: str = _text(60)
    timer: StoryTimer | None = None
    choices: list[StoryChoice] = Field(default_factory=list, max_length=MAX_CHOICES_PER_SEGMENT)
    routes: list[StoryRoute] = Field(default_factory=list, max_length=MAX_ROUTES_PER_SEGMENT)
    position: StoryPosition | None = None


class StoryGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = _text(120)
    synopsis: str = _text(2000)
    outline: list[Annotated[str, StringConstraints(max_length=400)]] = Field(default_factory=list, max_length=30)
    start: str = Field(default="", max_length=64)
    variables: list[StoryVariable] = Field(default_factory=list, max_length=MAX_VARIABLES)
    segments: list[StorySegment] = Field(default_factory=list, max_length=MAX_SEGMENTS)

    @model_validator(mode="after")
    def _identity(self) -> "StoryGraph":
        _unique("变量", [item.id for item in self.variables])
        _unique("片段", [item.id for item in self.segments])
        # Statistics are keyed by choice id, so a blank one gets a name here and a repeated one is refused.
        taken = {choice.id for segment in self.segments for choice in segment.choices if choice.id}
        taken |= {route.id for segment in self.segments for route in segment.routes if route.id}
        for segment in self.segments:
            for prefix, edges in (("c", segment.choices), ("r", segment.routes)):
                for index, edge in enumerate(edges, start=1):
                    if edge.id:
                        continue
                    edge.id = _fresh_id(f"{segment.id}.{prefix}{index}", taken)
                    taken.add(edge.id)
        _unique("选项或路由", [
            edge.id for segment in self.segments for edge in (*segment.choices, *segment.routes)
        ])
        for edge in (edge for segment in self.segments for edge in (*segment.choices, *segment.routes)):
            _check_id(edge.id)
            if edge.condition is not None:
                _check_condition_size(edge.condition)
        return self


def _unique(label: str, ids: Sequence[str]) -> None:
    repeated = [item for item, count in Counter(ids).items() if count > 1]
    if repeated:
        raise ValueError(f"{label}编号重复：{', '.join(repeated[:5])}")


def _fresh_id(base: str, taken: set[str]) -> str:
    candidate, suffix = base[:72], 1
    while candidate in taken:
        suffix += 1
        candidate = f"{base[:72]}-{suffix}"
    return candidate


def _check_condition_size(condition: Condition) -> None:
    nodes = 0

    def walk(item: Condition, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > MAX_CONDITION_DEPTH:
            raise ValueError(f"条件最多嵌套 {MAX_CONDITION_DEPTH} 层")
        if nodes > MAX_CONDITION_NODES:
            raise ValueError(f"一个条件最多 {MAX_CONDITION_NODES} 项")
        for child in (item.all or item.any or []):
            walk(child, depth + 1)

    walk(condition, 1)


def format_errors(error: ValidationError, limit: int = 6) -> str:
    parts = []
    for item in error.errors()[:limit]:
        where = ".".join(str(part) for part in item.get("loc", ()))
        parts.append(f"{where or '(根)'}: {item.get('msg', '')}")
    return "；".join(parts)


def parse_graph(raw: Any) -> dict[str, Any]:
    """The stored form of a graph, or :class:`StoryInputError` saying what is wrong with it."""
    try:
        graph = StoryGraph.model_validate(raw).model_dump(mode="json")
    except ValidationError as error:
        raise StoryInputError(f"互动剧数据不合法：{format_errors(error)}") from error
    if len(json.dumps(graph, ensure_ascii=False).encode("utf-8")) > MAX_GRAPH_JSON_BYTES:
        raise StoryInputError(f"互动剧数据超过 {MAX_GRAPH_JSON_BYTES // (1024 * 1024)} MB 上限")
    return graph


def media_urls(graph: Mapping[str, Any]) -> set[str]:
    return {
        str(segment["media"]["url"]) for segment in graph.get("segments") or []
        if isinstance(segment.get("media"), Mapping) and segment["media"].get("url")
    }


# --------------------------------------------------------------------------- the rules


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compare(actual: Any, op: str, expected: Any) -> bool:
    """One comparison. Mismatched types are false for every operator, ``ne`` included."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        if not (isinstance(actual, bool) and isinstance(expected, bool)):
            return False
        return actual == expected if op == "eq" else actual != expected if op == "ne" else False
    if not (_is_number(actual) and _is_number(expected)):
        return False
    return {
        "eq": actual == expected, "ne": actual != expected, "gt": actual > expected,
        "gte": actual >= expected, "lt": actual < expected, "lte": actual <= expected,
    }.get(op, False)


def evaluate(condition: Mapping[str, Any] | None, values: Mapping[str, Any]) -> bool:
    if not condition:
        return True
    if condition.get("all") is not None:
        return all(evaluate(item, values) for item in condition["all"])
    if condition.get("any") is not None:
        return any(evaluate(item, values) for item in condition["any"])
    name = condition.get("var")
    return name in values and compare(values[name], str(condition.get("op")), condition.get("value"))


def _round(value: float) -> float:
    # Math.round's rule (not Python's banker's rounding), so a 0.1 + 0.2 settles the same in the players.
    return math.floor(value * 1e6 + 0.5) / 1e6


def _clamp(value: float, variable: Mapping[str, Any]) -> float:
    low, high = variable.get("min"), variable.get("max")
    if low is not None:
        value = max(value, low)
    if high is not None:
        value = min(value, high)
    return value


def initial_values(graph: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for variable in graph.get("variables") or []:
        initial = variable.get("initial")
        values[variable["id"]] = initial if variable.get("kind") == "flag" else _clamp(initial or 0, variable)
    return values


def apply_effects(effects: Iterable[Mapping[str, Any]], values: Mapping[str, Any], variables: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """A new set of values; an effect on an unknown variable or of the wrong type is ignored (and reported)."""
    result = dict(values)
    for effect in effects:
        variable = variables.get(effect.get("var"))
        if variable is None:
            continue
        name, op, value = effect["var"], effect.get("op"), effect.get("value")
        if variable.get("kind") == "flag":
            if op == "set" and isinstance(value, bool):
                result[name] = value
        elif _is_number(value):
            base = result.get(name, 0) if op == "add" else 0
            result[name] = _clamp(_round(base + value), variable)
    return result


def _index(graph: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {segment["id"]: segment for segment in graph.get("segments") or []}


def _variables(graph: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {variable["id"]: variable for variable in graph.get("variables") or []}


def step(segment: Mapping[str, Any], values: Mapping[str, Any], known: Mapping[str, Any]) -> tuple[str, Any]:
    """What happens after a segment: ``ending``, a matched ``route``, the open ``choices``, or ``stuck``."""
    if segment.get("kind") == "ending":
        return "ending", None
    for route in segment.get("routes") or []:
        if route.get("target") in known and evaluate(route.get("condition"), values):
            return "route", route
    options = [
        choice for choice in segment.get("choices") or []
        if choice.get("target") in known and evaluate(choice.get("condition"), values)
    ]
    return ("choices", options) if options else ("stuck", None)


# --------------------------------------------------------------------------- what a variable can hold


VALUE_SET_LIMIT = 16
# After this many widenings a node's growing bounds jump to the variable's limits, so loops settle.
WIDEN_AFTER = 24
FLOW_ITERATION_LIMIT = 5000


@dataclass(frozen=True)
class Domain:
    """Every value a variable can hold at a point: an exact small set, or an interval once that grows."""

    values: frozenset[Any] | None = None
    low: float = -math.inf
    high: float = math.inf
    low_open: bool = False
    high_open: bool = False

    @property
    def bounds(self) -> tuple[float, float]:
        if self.values is None:
            return self.low, self.high
        numbers = [value for value in self.values if _is_number(value)]
        return (min(numbers), max(numbers)) if numbers else (-math.inf, math.inf)


def _hull(low: float, high: float) -> Domain:
    return Domain(None, low, high)


def _join(first: Domain, second: Domain) -> Domain:
    if first.values is not None and second.values is not None:
        merged = first.values | second.values
        if len(merged) <= VALUE_SET_LIMIT or any(isinstance(value, bool) for value in merged):
            return Domain(merged)
    return _hull(min(first.bounds[0], second.bounds[0]), max(first.bounds[1], second.bounds[1]))


def _widen(old: Domain, new: Domain, variable: Mapping[str, Any]) -> Domain:
    """Stop a loop counting forever: whichever bound still moves goes straight to the variable's limit."""
    if variable.get("kind") == "flag":
        return new
    low, high = new.bounds
    if low < old.bounds[0]:
        low = variable["min"] if variable.get("min") is not None else -math.inf
    if high > old.bounds[1]:
        high = variable["max"] if variable.get("max") is not None else math.inf
    return _hull(low, high)


def _apply_to_domain(domain: Domain, effect: Mapping[str, Any], variable: Mapping[str, Any]) -> Domain:
    op, value = effect.get("op"), effect.get("value")
    if variable.get("kind") == "flag":
        return Domain(frozenset({value})) if op == "set" and isinstance(value, bool) else domain
    if not _is_number(value):
        return domain
    if op == "set":
        return Domain(frozenset({_clamp(_round(value), variable)}))
    if domain.values is not None:
        return Domain(frozenset(_clamp(_round(item + value), variable) for item in domain.values))
    return _hull(_clamp(domain.low + value, variable), _clamp(domain.high + value, variable))


def _restrict(domain: Domain, op: str, value: Any) -> Domain | None:
    """The part of a domain for which the comparison holds; ``None`` when no value can make it true."""
    if domain.values is not None:
        kept = frozenset(item for item in domain.values if compare(item, op, value))
        return Domain(kept) if kept else None
    if not _is_number(value):
        return None
    low, high, low_open, high_open = domain.low, domain.high, domain.low_open, domain.high_open
    if op == "eq":
        inside = (low < value or (low == value and not low_open)) and (value < high or (value == high and not high_open))
        return Domain(frozenset({value})) if inside else None
    if op == "ne":
        return None if low == high == value else domain
    if op in ("gt", "gte"):
        if value > low or (value == low and op == "gt"):
            low, low_open = value, op == "gt"
    elif op in ("lt", "lte"):
        if value < high or (value == high and op == "lt"):
            high, high_open = value, op == "lt"
    else:
        return None
    if low > high or (low == high and (low_open or high_open)):
        return None
    return Domain(None, low, high, low_open, high_open)


def can_be_true(condition: Mapping[str, Any] | None, state: Mapping[str, Domain]) -> bool:
    """False only when no value the variables can hold satisfies the condition, never by mistake.

    Variables are treated as independent, so a condition that fails only because two variables
    always move together still counts as possible; ``all`` narrows one variable across its
    comparisons, which is what catches ``x > 5 and x < 3``.
    """
    if not condition:
        return True
    if condition.get("any") is not None:
        return any(can_be_true(item, state) for item in condition["any"])
    if condition.get("all") is not None:
        narrowed = dict(state)
        groups = []
        for item in condition["all"]:
            if item.get("var") is None:
                groups.append(item)
                continue
            domain = narrowed.get(item["var"])
            kept = _restrict(domain, str(item.get("op")), item.get("value")) if domain is not None else None
            if kept is None:
                return False
            narrowed[item["var"]] = kept
        return all(can_be_true(item, narrowed) for item in groups)
    domain = state.get(condition.get("var"))
    return domain is not None and _restrict(domain, str(condition.get("op")), condition.get("value")) is not None


def _describe(domain: Domain) -> str:
    if domain.values is not None:
        ordered = sorted(domain.values, key=lambda item: (isinstance(item, bool), item))
        return "、".join(("true" if item else "false") if isinstance(item, bool) else f"{item:g}" for item in ordered)
    low, high = domain.low, domain.high
    if math.isinf(low) and math.isinf(high):
        return "任意值"
    if math.isinf(low):
        return f"≤ {high:g}"
    if math.isinf(high):
        return f"≥ {low:g}"
    return f"{low:g} ~ {high:g}"


def _edges(segment: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every way out of a segment that its order allows: nothing after an unconditional route is ever used."""
    if segment.get("kind") == "ending":
        return []
    edges: list[dict[str, Any]] = []
    for route in segment.get("routes") or []:
        edges.append({"kind": "route", "id": route["id"], "condition": route.get("condition"), "target": route.get("target"), "effects": ()})
        if not route.get("condition"):
            return edges
    for choice in segment.get("choices") or []:
        edges.append({
            "kind": "choice", "id": choice["id"], "condition": choice.get("condition"),
            "target": choice.get("target"), "effects": choice.get("effects") or (), "text": choice.get("text") or "",
        })
    return edges


@dataclass
class Flow:
    """The result of walking the graph with sets of values instead of one playthrough's values."""

    states: dict[str, dict[str, Domain]]
    live: dict[str, list[dict[str, Any]]]
    impossible: list[tuple[str, dict[str, Any]]]


def flow_values(graph: Mapping[str, Any]) -> Flow:
    """Forward over the graph until nothing changes; an edge only counts once its condition can hold.

    Conditions never narrow what flows past them and effects apply whatever else happened on the
    way, so each state only ever over-estimates: what this calls impossible really is.
    """
    index, variables = _index(graph), _variables(graph)
    start = graph.get("start")
    states: dict[str, dict[str, Domain]] = {}
    if start in index:
        states[start] = {name: Domain(frozenset({value})) for name, value in initial_values(graph).items()}
    pending = deque(states)
    updates: Counter[str] = Counter()
    iterations = 0
    while pending:
        current = pending.popleft()
        iterations += 1
        state = states[current]
        for edge in _edges(index[current]):
            target = edge["target"]
            if target not in index or not can_be_true(edge["condition"], state):
                continue
            outgoing = dict(state)
            for effect in edge["effects"]:
                variable = variables.get(effect.get("var"))
                if variable is not None:
                    outgoing[effect["var"]] = _apply_to_domain(outgoing[effect["var"]], effect, variable)
            known = states.get(target)
            if known is None:
                states[target] = outgoing
                pending.append(target)
                continue
            force = iterations > FLOW_ITERATION_LIMIT
            changed = False
            merged = dict(known)
            for name, domain in outgoing.items():
                old = known[name]
                joined = _join(old, domain)
                if joined == old:
                    continue
                if force or updates[target] >= WIDEN_AFTER:
                    joined = _widen(old, joined, variables[name])
                if joined != old:
                    merged[name] = joined
                    changed = True
            if changed:
                states[target] = merged
                updates[target] += 1
                if target not in pending:
                    pending.append(target)
    live: dict[str, list[dict[str, Any]]] = {}
    impossible: list[tuple[str, dict[str, Any]]] = []
    for segment_id, state in states.items():
        live[segment_id] = []
        for edge in _edges(index[segment_id]):
            if can_be_true(edge["condition"], state):
                if edge["target"] in index:
                    live[segment_id].append(edge)
            else:
                impossible.append((segment_id, edge))
    return Flow(states, live, impossible)


def _components(nodes: Iterable[str], successors: Mapping[str, Sequence[str]]) -> list[list[str]]:
    """Tarjan's strongly connected components, iterative: a long chain must not hit the recursion limit."""
    order: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    found: list[list[str]] = []
    counter = 0
    for root in nodes:
        if root in order:
            continue
        order[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(successors.get(root, ())))]
        while work:
            node, children = work[-1]
            for child in children:
                if child not in order:
                    order[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(successors.get(child, ()))))
                    break
                if child in on_stack:
                    low[node] = min(low[node], order[child])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
                if low[node] == order[node]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    found.append(component)
    return found


# --------------------------------------------------------------------------- validation


def _issue(code: str, severity: str, message: str, **fields: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **{key: value for key, value in fields.items() if value is not None}}


def _leaves(condition: Mapping[str, Any] | None) -> Iterable[Mapping[str, Any]]:
    if not condition:
        return
    children = condition.get("all") if condition.get("all") is not None else condition.get("any")
    if children is not None:
        for child in children:
            yield from _leaves(child)
    else:
        yield condition


def _condition_is_wellformed(condition: Mapping[str, Any] | None, variables: Mapping[str, Mapping[str, Any]]) -> bool:
    return all(_leaf_problem(leaf, variables) is None for leaf in _leaves(condition))


def _leaf_problem(leaf: Mapping[str, Any], variables: Mapping[str, Mapping[str, Any]]) -> str | None:
    variable = variables.get(leaf.get("var"))
    if variable is None:
        return "unknown"
    value = leaf.get("value")
    if variable.get("kind") == "flag":
        return None if isinstance(value, bool) and leaf.get("op") in ("eq", "ne") else "type"
    return None if _is_number(value) else "type"


def _segment_name(segment: Mapping[str, Any]) -> str:
    return str(segment.get("title") or segment.get("id") or "")


def _check_references(segment: Mapping[str, Any], variables: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    name = _segment_name(segment)
    edges = [("choice", item) for item in segment.get("choices") or []] + [("route", item) for item in segment.get("routes") or []]
    for kind, edge in edges:
        where = {f"{kind}_id": edge["id"], "segment_id": segment["id"]}
        for leaf in _leaves(edge.get("condition")):
            problem = _leaf_problem(leaf, variables)
            params = {"segment": name, "variable": str(leaf.get("var"))}
            if problem == "unknown":
                issues.append(_issue("unknown_variable", "error", f"「{name}」的条件用了不存在的变量 {leaf.get('var')}", variable_id=leaf.get("var"), params=params, **where))
            elif problem == "type":
                issues.append(_issue("condition_type_mismatch", "error", f"「{name}」的条件与变量 {leaf.get('var')} 的类型不符", variable_id=leaf.get("var"), params=params, **where))
        for effect in edge.get("effects") or []:
            variable = variables.get(effect.get("var"))
            params = {"segment": name, "variable": str(effect.get("var"))}
            if variable is None:
                issues.append(_issue("unknown_variable", "error", f"「{name}」的效果用了不存在的变量 {effect.get('var')}", variable_id=effect.get("var"), params=params, **where))
            elif variable.get("kind") == "flag" and not (effect.get("op") == "set" and isinstance(effect.get("value"), bool)):
                issues.append(_issue("effect_type_mismatch", "error", f"「{name}」的效果对标记变量 {effect.get('var')} 只能设为 true 或 false", variable_id=effect.get("var"), params=params, **where))
            elif variable.get("kind") != "flag" and not _is_number(effect.get("value")):
                issues.append(_issue("effect_type_mismatch", "error", f"「{name}」的效果给数值变量 {effect.get('var')} 赋了非数值", variable_id=effect.get("var"), params=params, **where))
    return issues


def _check_exits(segment: Mapping[str, Any], index: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    name = _segment_name(segment)
    choices, routes = segment.get("choices") or [], segment.get("routes") or []
    if segment.get("kind") == "ending":
        if choices or routes:
            issues.append(_issue("ending_has_exits", "warning", f"结局「{name}」还连着出口，播放到结局时会被忽略", segment_id=segment["id"], params={"segment": name}))
        return issues
    if not choices and not routes:
        issues.append(_issue("dead_end", "error", f"「{name}」没有任何出口，也不是结局", segment_id=segment["id"], params={"segment": name}))
    for choice in choices:
        params = {"segment": name, "text": str(choice.get("text") or "")}
        if not choice.get("target"):
            issues.append(_issue("choice_unconnected", "error", f"「{name}」的选项「{params['text']}」还没有连到任何片段", segment_id=segment["id"], choice_id=choice["id"], params=params))
        elif choice["target"] not in index:
            issues.append(_issue("choice_target_missing", "error", f"「{name}」的选项「{params['text']}」指向不存在的片段 {choice['target']}", segment_id=segment["id"], choice_id=choice["id"], params={**params, "target": choice["target"]}))
        if not str(choice.get("text") or "").strip():
            issues.append(_issue("choice_text_empty", "warning", f"「{name}」有一个选项没有文字", segment_id=segment["id"], choice_id=choice["id"], params={"segment": name}))
    for route in routes:
        if not route.get("target") or route["target"] not in index:
            issues.append(_issue("route_target_missing", "error", f"「{name}」的自动路由没有连到存在的片段", segment_id=segment["id"], route_id=route["id"], params={"segment": name}))
    used = {edge["id"] for edge in _edges(segment)}
    shadowed = [edge["id"] for edge in (*routes, *choices) if edge["id"] not in used]
    if shadowed:
        issues.append(_issue("shadowed_edges", "warning", f"「{name}」有无条件路由，排在它后面的 {len(shadowed)} 个出口永远用不上", segment_id=segment["id"], params={"segment": name, "count": len(shadowed)}))
    return issues


def _check_timer(segment: Mapping[str, Any]) -> list[dict[str, Any]]:
    timer = segment.get("timer")
    if not timer:
        return []
    name = _segment_name(segment)
    choices = segment.get("choices") or []
    if not choices:
        return [_issue("timer_without_choices", "warning", f"「{name}」设了限时但没有选项", segment_id=segment["id"], params={"segment": name})]
    default = next((choice for choice in choices if choice["id"] == timer.get("default_choice")), None)
    if default is None:
        return [_issue("timer_default_missing", "error", f"「{name}」的限时没有默认选项", segment_id=segment["id"], params={"segment": name})]
    if default.get("condition"):
        return [_issue("timer_default_gated", "warning", f"「{name}」的限时默认选项带条件；不满足时会改走第一个可选项", segment_id=segment["id"], choice_id=default["id"], params={"segment": name})]
    return []


def validate_graph(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Everything wrong with a story, as data the editor can point at. ``error`` blocks an export."""
    segments = graph.get("segments") or []
    if not segments:
        return [_issue("empty_story", "error", "故事里还没有片段")]
    index, variables = _index(graph), _variables(graph)
    issues: list[dict[str, Any]] = []
    if graph.get("start") not in index:
        issues.append(_issue("missing_start", "error", "没有指定存在的开场片段"))
    for segment in segments:
        issues.extend(_check_references(segment, variables))
        issues.extend(_check_exits(segment, index))
        issues.extend(_check_timer(segment))
    flow = flow_values(graph)
    reachable = set(flow.states)
    connected = _structurally_reachable(graph)
    if graph.get("start") in index:
        for segment in segments:
            if segment["id"] not in reachable:
                by_condition = segment["id"] in connected
                reason = "它的入口条件永远满足不了" if by_condition else "没有路径从开场走到这里"
                issues.append(_issue(
                    "unreachable_segment", "warning", f"「{_segment_name(segment)}」到不了：{reason}", segment_id=segment["id"],
                    params={"segment": _segment_name(segment), "reason": "conditions" if by_condition else "no_path"},
                ))
    for segment_id, edge in flow.impossible:
        if not _condition_is_wellformed(edge["condition"], variables):
            continue
        name = _segment_name(index[segment_id])
        possible = "；".join(
            f"{leaf['var']} 只可能是 {_describe(flow.states[segment_id][leaf['var']])}"
            for leaf in {str(item.get("var")): item for item in _leaves(edge["condition"])}.values()
        )
        label = edge.get("text") or edge["id"]
        issues.append(_issue(
            "impossible_condition", "warning", f"「{name}」的「{label}」条件永远不会成立：{possible}", segment_id=segment_id,
            **{f"{edge['kind']}_id": edge["id"]}, params={"segment": name, "text": str(label), "possible": possible},
        ))
    issues.extend(_check_endings_and_cycles(graph, flow, issues))
    return issues


def _structurally_reachable(graph: Mapping[str, Any]) -> set[str]:
    index = _index(graph)
    seen: set[str] = set()
    pending = [graph.get("start")] if graph.get("start") in index else []
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(edge["target"] for edge in _edges(index[current]) if edge["target"] in index)
    return seen


def _check_endings_and_cycles(graph: Mapping[str, Any], flow: Flow, existing: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    index = _index(graph)
    issues: list[dict[str, Any]] = []
    endings = [segment["id"] for segment in graph.get("segments") or [] if segment.get("kind") == "ending"]
    reachable = set(flow.states)
    if not endings:
        issues.append(_issue("no_ending", "error", "故事里还没有结局"))
    elif graph.get("start") in index and not reachable.intersection(endings):
        issues.append(_issue("no_reachable_ending", "error", "从开场走不到任何结局"))
    successors = {node: [edge["target"] for edge in flow.live.get(node, [])] for node in reachable}
    trapped: set[str] = set()
    for component in _components(sorted(reachable), successors):
        members = set(component)
        looping = len(component) > 1 or component[0] in successors.get(component[0], ())
        if not looping or any(index[node].get("kind") == "ending" for node in component):
            continue
        if not any(target not in members for node in component for target in successors.get(node, ())):
            ordered = sorted(component)
            names = "、".join(_segment_name(index[node]) for node in ordered[:6])
            trapped |= members
            issues.append(_issue(
                "cycle_no_exit", "error", f"这些片段绕成一个圈且没有出口：{names}", segment_id=ordered[0], segment_ids=ordered,
                params={"segments": names},
            ))
    # Whatever else leads only into a trap: without this a segment one step before the loop looks fine.
    can_finish = set(endings) & reachable
    predecessors: dict[str, list[str]] = {}
    for node, targets in successors.items():
        for target in targets:
            predecessors.setdefault(target, []).append(node)
    pending = list(can_finish)
    while pending:
        for parent in predecessors.get(pending.pop(), ()):
            if parent not in can_finish:
                can_finish.add(parent)
                pending.append(parent)
    flagged = {item.get("segment_id") for item in existing if item.get("severity") == "error"} | trapped
    if endings and reachable.intersection(endings):
        for node in sorted(reachable - can_finish - flagged):
            name = _segment_name(index[node])
            issues.append(_issue("cannot_reach_ending", "warning", f"从「{name}」出发走不到任何结局", segment_id=node, params={"segment": name}))
    return issues


# --------------------------------------------------------------------------- paths


def reading_seconds(text: str) -> float:
    """Roughly how long a line takes to perform: about 4.5 CJK characters or 2.5 Latin words a second."""
    cjk = len(re.findall(r"[㐀-鿿぀-ヿ가-힣]", text or ""))
    words = len(re.findall(r"[A-Za-zÀ-ỹ0-9']+", text or ""))
    return cjk / 4.5 + words / 2.5


def segment_seconds(segment: Mapping[str, Any]) -> float:
    media = segment.get("media") if isinstance(segment.get("media"), Mapping) else None
    if media and media.get("kind") == "video" and float(media.get("duration_s") or 0) > 0:
        return float(media["duration_s"])
    if segment.get("est_seconds"):
        return float(segment["est_seconds"])
    spoken = " ".join([str(segment.get("narration") or ""), *(str(line.get("text") or "") for line in segment.get("dialogue") or [])])
    return max(3.0, reading_seconds(spoken))


def decision_seconds(segment: Mapping[str, Any]) -> float:
    choices = segment.get("choices") or []
    if segment.get("kind") == "ending" or not choices:
        return 0.0
    timer = segment.get("timer")
    return float(timer["seconds"]) if timer else 3.0


def route_key(steps: Iterable[Sequence[Any]]) -> str:
    """One playthrough's identity: the same segments reached through the same choices."""
    text = "\x1f".join(f"{segment}\x1e{via or ''}" for segment, via in steps)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


MAX_PATHS = 2000
MAX_PATH_STEPS = 30_000
LOOP_LIMIT = 2
ROUTES_SHOWN = 100
SIMULATION_RUNS = 500
SIMULATION_MAX_STEPS = 300


def _ratio(part: int | float, whole: int | float) -> float:
    return round(part / whole, 4) if whole else 0.0


def _enumerate(graph: Mapping[str, Any], *, max_paths: int, max_steps: int, loop_limit: int) -> dict[str, Any]:
    """Depth first over real playthroughs, with each open choice equally likely; every loop is cut at ``loop_limit`` visits."""
    index, variables = _index(graph), _variables(graph)
    routes: list[dict[str, Any]] = []
    stuck: dict[str, dict[str, Any]] = {}
    tally = {"paths": 0, "stuck_paths": 0, "loop_cuts": 0, "complete": 0, "stuck_mass": 0.0, "loop_mass": 0.0}
    steps_taken = 0
    truncated = False
    path: list[tuple[str, str | None]] = []
    visits: Counter[str] = Counter()
    stack: list[tuple[str, Any]] = []
    if graph.get("start") in index:
        stack.append(("enter", (graph["start"], None, initial_values(graph), 1.0)))
    while stack:
        action, payload = stack.pop()
        if action == "leave":
            path.pop()
            visits[payload] -= 1
            continue
        segment_id, via, values, mass = payload
        steps_taken += 1
        if steps_taken > max_steps or tally["paths"] >= max_paths:
            truncated = True
            break
        if visits[segment_id] >= loop_limit:
            tally["loop_cuts"] += 1
            tally["paths"] += 1
            tally["loop_mass"] += mass
            continue
        visits[segment_id] += 1
        path.append((segment_id, via))
        stack.append(("leave", segment_id))
        segment = index[segment_id]
        outcome, detail = step(segment, values, index)
        if outcome == "ending":
            tally["paths"] += 1
            tally["complete"] += 1
            seconds = sum(segment_seconds(index[item]) + decision_seconds(index[item]) for item, _ in path)
            routes.append({
                "key": route_key(path), "ending_id": segment_id,
                "segments": [item for item, _ in path], "choices": [item for _, item in path if item],
                "seconds": round(seconds, 1), "minutes": round(seconds / 60, 2), "probability": mass,
            })
        elif outcome == "route":
            stack.append(("enter", (detail["target"], None, values, mass)))
        elif outcome == "choices":
            share = mass / len(detail)
            for choice in reversed(detail):
                stack.append(("enter", (choice["target"], choice["id"], apply_effects(choice.get("effects") or [], values, variables), share)))
        else:
            tally["paths"] += 1
            tally["stuck_paths"] += 1
            tally["stuck_mass"] += mass
            stuck.setdefault(segment_id, {"segment_id": segment_id, "values": dict(values)})
    return {"routes": routes, "stuck": list(stuck.values()), "tally": tally, "truncated": truncated}


def _simulate(graph: Mapping[str, Any], *, runs: int, max_steps: int, seed: int) -> dict[str, Any]:
    """Random playthroughs, for when loops or sheer size stop enumeration giving honest rates."""
    index, variables = _index(graph), _variables(graph)
    rng = random.Random(seed)
    endings: Counter[str] = Counter()
    unfinished = 0
    for _ in range(runs):
        current, values = graph.get("start"), initial_values(graph)
        for _ in range(max_steps):
            outcome, detail = step(index[current], values, index)
            if outcome == "ending":
                endings[current] += 1
                break
            if outcome == "route":
                current = detail["target"]
            elif outcome == "choices":
                choice = rng.choice(detail)
                values = apply_effects(choice.get("effects") or [], values, variables)
                current = choice["target"]
            else:
                unfinished += 1
                break
        else:
            unfinished += 1
    return {"endings": endings, "unfinished": unfinished, "runs": runs}


def analyze_paths(
    graph: Mapping[str, Any], *, max_paths: int = MAX_PATHS, max_steps: int = MAX_PATH_STEPS, loop_limit: int = LOOP_LIMIT,
    simulation_runs: int = SIMULATION_RUNS, seed: int = 7,
) -> dict[str, Any]:
    """Bounded answers to "how much of this story can be seen, and how often does each ending happen"."""
    index = _index(graph)
    walked = _enumerate(graph, max_paths=max_paths, max_steps=max_steps, loop_limit=loop_limit)
    routes, tally = walked["routes"], walked["tally"]
    endings_all = [segment for segment in graph.get("segments") or [] if segment.get("kind") == "ending"]
    # Enumeration is exact only when nothing was cut; otherwise its masses understate what loops lead to.
    exact = not walked["truncated"] and tally["loop_cuts"] == 0
    rates: dict[str, float] = Counter()
    if exact or graph.get("start") not in index:
        for route in routes:
            rates[route["ending_id"]] += route["probability"]
        unfinished = tally["stuck_mass"]
    else:
        simulated = _simulate(graph, runs=simulation_runs, max_steps=SIMULATION_MAX_STEPS, seed=seed)
        rates = {key: count / simulated["runs"] for key, count in simulated["endings"].items()}
        unfinished = simulated["unfinished"] / simulated["runs"]
    ending_rows = []
    for ending in endings_all:
        mine = [route for route in routes if route["ending_id"] == ending["id"]]
        weight = sum(route["probability"] for route in mine)
        minutes = [route["minutes"] for route in mine]
        ending_rows.append({
            "id": ending["id"], "title": _segment_name(ending), "label": ending.get("ending_label") or "",
            "paths": len(mine), "reach_rate": round(rates.get(ending["id"], 0.0), 4),
            "min_minutes": min(minutes) if minutes else None, "max_minutes": max(minutes) if minutes else None,
            "avg_minutes": round(sum(route["minutes"] * route["probability"] for route in mine) / weight, 2) if weight else None,
        })
    covered_segments = {segment for route in routes for segment in route["segments"]}
    covered_choices = {choice for route in routes for choice in route["choices"]}
    all_choices = [choice for segment in graph.get("segments") or [] if segment.get("kind") != "ending" for choice in segment.get("choices") or []]
    covered_endings = {route["ending_id"] for route in routes}
    segment_total, choice_total = len(index), len(all_choices)
    total_weight = sum(route["probability"] for route in routes)
    minutes_all = [route["minutes"] for route in routes]
    shown = sorted(routes, key=lambda route: (-route["probability"], route["seconds"]))[:ROUTES_SHOWN]
    return {
        "paths": tally["paths"], "complete_paths": tally["complete"], "stuck_paths": tally["stuck_paths"],
        "loop_cuts": tally["loop_cuts"], "truncated": walked["truncated"], "max_paths": max_paths, "loop_limit": loop_limit,
        "rate_method": "enumeration" if exact else "simulation",
        "coverage": {
            "segments_covered": len(covered_segments), "segments_total": segment_total, "segments_ratio": _ratio(len(covered_segments), segment_total),
            "choices_covered": len(covered_choices), "choices_total": choice_total, "choices_ratio": _ratio(len(covered_choices), choice_total),
            "endings_covered": len(covered_endings), "endings_total": len(endings_all), "endings_ratio": _ratio(len(covered_endings), len(endings_all)),
        },
        "endings": ending_rows,
        "unfinished_rate": round(unfinished, 4),
        "minutes": {
            "min": min(minutes_all) if minutes_all else None, "max": max(minutes_all) if minutes_all else None,
            "avg": round(sum(route["minutes"] * route["probability"] for route in routes) / total_weight, 2) if total_weight else None,
        },
        "routes": [{**route, "probability": round(route["probability"], 4)} for route in shown],
        "route_keys": [route["key"] for route in routes],
        "stuck": walked["stuck"][:10],
    }


def analyze_story(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Validation and path analysis together, as the editor shows them."""
    issues = validate_graph(graph)
    paths = analyze_paths(graph)
    index = _index(graph)
    for item in paths["stuck"]:
        name = _segment_name(index[item["segment_id"]])
        issues.append(_issue(
            "stuck_state", "warning", f"有的走法到了「{name}」时所有选项都上了锁，只能停在那里", segment_id=item["segment_id"],
            params={"segment": name},
        ))
    errors = sum(1 for item in issues if item["severity"] == "error")
    return {"issues": issues, "errors": errors, "warnings": len(issues) - errors, "ready": errors == 0, "paths": paths}


# --------------------------------------------------------------------------- playtest statistics


MAX_ROUTE_KEYS = 1000
MAX_PLAYTEST_STEPS = 2000


def empty_stats() -> dict[str, Any]:
    return {"runs": 0, "completed": 0, "timeouts": 0, "choices": {}, "segments": {}, "endings": {}, "routes": {}}


def record_playtest(stats: Mapping[str, Any] | None, graph: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, Any]:
    """One playthrough added to the counters. Ids this story does not have are dropped, so the store stays bounded."""
    result = {**empty_stats(), **{key: value for key, value in (stats or {}).items()}}
    for key in ("choices", "segments", "endings", "routes"):
        result[key] = dict(result.get(key) or {})
    index = _index(graph)
    choice_ids = {choice["id"] for segment in graph.get("segments") or [] for choice in segment.get("choices") or []}
    steps = [item for item in run.get("steps") or [] if isinstance(item, Mapping)][:MAX_PLAYTEST_STEPS]
    if not steps:
        return result
    pairs: list[tuple[str, str | None]] = []
    for item in steps:
        segment, choice = str(item.get("segment") or ""), item.get("choice")
        if segment not in index:
            continue
        pairs.append((segment, str(choice) if choice else None))
        result["segments"][segment] = int(result["segments"].get(segment, 0)) + 1
        if choice and str(choice) in choice_ids:
            result["choices"][str(choice)] = int(result["choices"].get(str(choice), 0)) + 1
    if not pairs:
        return result
    result["runs"] = int(result.get("runs") or 0) + 1
    result["timeouts"] = int(result.get("timeouts") or 0) + max(0, min(int(run.get("timeouts") or 0), len(steps)))
    ending = str(run.get("ending") or "")
    if ending in index and index[ending].get("kind") == "ending" and pairs[-1][0] == ending:
        result["completed"] = int(result.get("completed") or 0) + 1
        result["endings"][ending] = int(result["endings"].get(ending, 0)) + 1
        # A replay from the middle is not a route through the story.
        if run.get("from_start", True):
            key = route_key(pairs)
            if key in result["routes"] or len(result["routes"]) < MAX_ROUTE_KEYS:
                result["routes"][key] = int(result["routes"].get(key, 0)) + 1
    return result


def stats_view(stats: Mapping[str, Any] | None, graph: Mapping[str, Any], paths: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The counters laid over the current graph: a deleted choice or segment simply stops being listed."""
    data = {**empty_stats(), **(stats or {})}
    segments = graph.get("segments") or []
    choices_rows = []
    for segment in segments:
        rows = segment.get("choices") or []
        total = sum(int(data["choices"].get(choice["id"], 0)) for choice in rows)
        for choice in rows:
            count = int(data["choices"].get(choice["id"], 0))
            if count:
                choices_rows.append({
                    "segment_id": segment["id"], "segment": _segment_name(segment), "choice_id": choice["id"],
                    "text": str(choice.get("text") or ""), "count": count, "share": _ratio(count, total),
                })
    endings = [segment for segment in segments if segment.get("kind") == "ending"]
    played = [segment["id"] for segment in segments if int(data["segments"].get(segment["id"], 0)) > 0]
    known_routes = set((paths or {}).get("route_keys") or [])
    played_routes = known_routes.intersection(data["routes"])
    return {
        "runs": int(data["runs"]), "completed": int(data["completed"]), "timeouts": int(data["timeouts"]),
        "choices": choices_rows,
        "endings": [{"id": segment["id"], "title": _segment_name(segment), "count": int(data["endings"].get(segment["id"], 0))} for segment in endings],
        "endings_reached": sum(1 for segment in endings if int(data["endings"].get(segment["id"], 0)) > 0),
        "endings_total": len(endings),
        "segments_played": len(played), "segments_total": len(segments),
        "routes_played": len(played_routes), "routes_total": len(known_routes),
        "route_coverage": _ratio(len(played_routes), len(known_routes)),
    }


# --------------------------------------------------------------------------- what the planner returns


def reassign_edge_ids(payload: Any) -> Any:
    """Models reuse ``c1`` in every segment. Edge ids are ours to give; the timer's default follows its choice."""
    if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
        return payload
    for segment in payload["segments"]:
        if not isinstance(segment, dict):
            continue
        # A layout is the editor's job, and media is only ever chosen from what the project already owns.
        segment.pop("position", None)
        segment.pop("media", None)
        renamed: dict[str, str] = {}
        name = str(segment.get("id") or "s")
        for prefix, key in (("c", "choices"), ("r", "routes")):
            edges = segment.get(key)
            if not isinstance(edges, list):
                continue
            for number, edge in enumerate(edges, start=1):
                if isinstance(edge, dict):
                    new_id = f"{name}.{prefix}{number}"
                    if edge.get("id"):
                        renamed[str(edge["id"])] = new_id
                    edge["id"] = new_id
                    if isinstance(edge.get("condition"), dict) and not edge["condition"]:
                        edge["condition"] = None
        timer = segment.get("timer")
        if isinstance(timer, dict):
            timer["default_choice"] = renamed.get(str(timer.get("default_choice") or ""), "")
    return payload


class StoryPlanDraft(StoryGraph):
    """What a model is asked for: the stored graph, except that ids on edges are assigned for it."""

    @model_validator(mode="before")
    @classmethod
    def _assign(cls, payload: Any) -> Any:
        return reassign_edge_ids(payload)


def declare_missing_variables(graph: dict[str, Any]) -> None:
    """A variable a model used but forgot to list costs one more paid round for nothing; declare it from its first use."""
    known = {variable["id"] for variable in graph.get("variables") or []}
    for segment in graph.get("segments") or []:
        for edge in (*(segment.get("choices") or []), *(segment.get("routes") or [])):
            used = [*_leaves(edge.get("condition")), *(edge.get("effects") or [])]
            for item in used:
                name = item.get("var")
                if name and name not in known and len(known) < MAX_VARIABLES:
                    flag = isinstance(item.get("value"), bool)
                    graph.setdefault("variables", []).append({
                        "id": name, "label": str(name), "kind": "flag" if flag else "number",
                        "initial": False if flag else 0, "min": None, "max": None,
                    })
                    known.add(name)


def plan_problems(graph: dict[str, Any], *, min_endings: int = 2) -> list[str]:
    """Why a drafted story would not do, in words the next round can act on; may repair it mechanically first."""
    declare_missing_variables(graph)
    index = _index(graph)
    if graph.get("start") not in index and graph.get("segments"):
        graph["start"] = graph["segments"][0]["id"]
    for segment in graph.get("segments") or []:
        timer = segment.get("timer")
        if timer and segment.get("choices") and not any(choice["id"] == timer.get("default_choice") for choice in segment["choices"]):
            timer["default_choice"] = segment["choices"][0]["id"]
    reasons = [item["message"] for item in validate_graph(graph) if item["severity"] == "error"]
    reached = set(flow_values(graph).states)
    endings = [segment for segment in graph.get("segments") or [] if segment.get("kind") == "ending" and segment["id"] in reached]
    if len(endings) < min_endings:
        reasons.append(f"至少需要 {min_endings} 个能走到的结局（kind 为 ending），现在只有 {len(endings)} 个")
    branching = [segment for segment in graph.get("segments") or [] if len(segment.get("choices") or []) >= 2]
    if not branching:
        reasons.append("至少需要一个带两个以上选项的抉择点")
    return reasons[:12]


# --------------------------------------------------------------------------- the exported player


PLAYER_TEXT: dict[str, dict[str, str]] = {
    "zh-CN": {
        "start": "开始观看", "resume": "继续观看", "restart": "重新开始", "map": "故事地图", "close": "返回",
        "continue": "继续", "skip": "跳过", "locked": "未解锁", "ending": "结局", "endings": "已达成结局",
        "played": "已看过", "unlocked": "已解锁", "unexplored": "未探索", "unknown": "？？？", "stuck": "这条路走不下去了。",
        "stats": "故事进度", "progress": "当前数值", "replay": "点已看过或已解锁的片段，可以从那里重看。", "reset": "清除进度", "onTrue": "是", "onFalse": "否",
    },
    "en": {
        "start": "Start watching", "resume": "Continue", "restart": "Start over", "map": "Story map", "close": "Back",
        "continue": "Continue", "skip": "Skip", "locked": "Locked", "ending": "Ending", "endings": "Endings reached",
        "played": "Watched", "unlocked": "Unlocked", "unexplored": "Unexplored", "unknown": "???", "stuck": "This path goes no further.",
        "stats": "Your progress", "progress": "Current values", "replay": "Pick a watched or unlocked segment to replay from there.", "reset": "Clear progress", "onTrue": "Yes", "onFalse": "No",
    },
    "vi": {
        "start": "Bắt đầu xem", "resume": "Xem tiếp", "restart": "Bắt đầu lại", "map": "Bản đồ câu chuyện", "close": "Quay lại",
        "continue": "Tiếp tục", "skip": "Bỏ qua", "locked": "Chưa mở khóa", "ending": "Kết thúc", "endings": "Kết thúc đã đạt",
        "played": "Đã xem", "unlocked": "Đã mở khóa", "unexplored": "Chưa khám phá", "unknown": "???", "stuck": "Con đường này không đi tiếp được.",
        "stats": "Tiến độ của bạn", "progress": "Giá trị hiện tại", "replay": "Chọn phân đoạn đã xem hoặc đã mở khóa để xem lại từ đó.", "reset": "Xóa tiến độ", "onTrue": "Có", "onFalse": "Không",
    },
}

SAFE_MEDIA_PATTERN = re.compile(r"^(data:(image/(png|jpeg|webp)|video/(mp4|webm));base64,[A-Za-z0-9+/=]+|media/[A-Za-z0-9._-]+)$")


def player_story(graph: Mapping[str, Any], media: Mapping[str, str]) -> dict[str, Any]:
    """Only what playback needs, with media rewritten to what travels with the file; nothing else leaves the project."""
    segments = []
    for segment in graph.get("segments") or []:
        original = segment.get("media") if isinstance(segment.get("media"), Mapping) else None
        source = media.get(str(original["url"])) if original else None
        segments.append({
            "id": segment["id"], "title": segment.get("title") or "", "kind": segment.get("kind") or "scene",
            "narration": segment.get("narration") or "", "ending_label": segment.get("ending_label") or "",
            "dialogue": [{"speaker": line.get("speaker") or "", "text": line.get("text") or ""} for line in segment.get("dialogue") or []],
            "media": {"kind": original["kind"], "src": source} if original and source and SAFE_MEDIA_PATTERN.match(source) else None,
            "timer": dict(segment["timer"]) if segment.get("timer") else None,
            "choices": [
                {key: choice.get(key) for key in ("id", "text", "target", "condition", "when_locked", "locked_hint", "effects")}
                for choice in segment.get("choices") or []
            ],
            "routes": [{key: route.get(key) for key in ("id", "condition", "target")} for route in segment.get("routes") or []],
        })
    story = {
        "title": graph.get("title") or "", "synopsis": graph.get("synopsis") or "", "start": graph.get("start") or "",
        "variables": [{key: variable.get(key) for key in ("id", "label", "kind", "initial", "min", "max")} for variable in graph.get("variables") or []],
        "segments": segments,
    }
    # Media is hashed by address, not content: re-exporting the same story keeps a viewer's saved progress.
    story["fingerprint"] = hashlib.sha256(json.dumps(
        {**story, "segments": [{**segment, "media": None} for segment in segments]}, ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")).hexdigest()[:16]
    return story


def script_json(value: Any) -> str:
    """JSON that cannot end its <script> element or open a comment, whatever the story says."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for raw, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        text = text.replace(raw, escaped)
    return text


def render_player_html(story: Mapping[str, Any], *, lang: str = "zh-CN", bundled: bool = False) -> str:
    """One file that plays the story. ``bundled`` allows ``media/…`` beside it; otherwise only what is inlined."""
    if lang not in PLAYER_TEXT:
        lang = "zh-CN"
    # The policy is the promise made real: whatever a story says, this page cannot fetch anything from anywhere.
    sources = "'self' file: data: blob:" if bundled else "data: blob:"
    policy = (
        f"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src {sources}; media-src {sources}; "
        "base-uri 'none'; form-action 'none'"
    )
    fields = {
        "LANG": html.escape(lang, quote=True),
        "POLICY": html.escape(policy, quote=True),
        "TITLE": html.escape(str(story.get("title") or "Interactive story"), quote=True),
        "CSS": PLAYER_CSS,
        "STORY": script_json(story),
        "CHROME": script_json(PLAYER_TEXT[lang]),
        "ENGINE": PLAYER_ENGINE_JS,
        "UI": PLAYER_UI_JS,
    }
    # One pass over the template, so a story containing "%%UI%%" stays words.
    return re.sub(r"%%([A-Z]+)%%", lambda match: fields[match.group(1)], PLAYER_TEMPLATE)


PLAYER_TEMPLATE = """<!doctype html>
<html lang="%%LANG%%">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="%%POLICY%%">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>%%TITLE%%</title>
<style>%%CSS%%</style>
</head>
<body>
<main id="app" aria-live="polite"></main>
<script type="application/json" id="story-data">%%STORY%%</script>
<script type="application/json" id="story-chrome">%%CHROME%%</script>
<script>%%ENGINE%%</script>
<script>%%UI%%</script>
</body>
</html>
"""

PLAYER_CSS = """
:root{color-scheme:light dark;--bg:#fbf7f8;--surface:#fff;--line:#e7dbe0;--ink:#2a1d23;--muted:#75636b;--accent:#d63d66;--on-accent:#fff;--good:#14865c}
@media (prefers-color-scheme:dark){:root{--bg:#141013;--surface:#201a1e;--line:#3a3036;--ink:#f3ecef;--muted:#b3a4ab;--accent:#f06a8e;--on-accent:#1b0f14;--good:#4fcb9b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 system-ui,-apple-system,"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 56px;min-height:100vh}
h1{font-size:1.5rem;line-height:1.3;margin:0 0 12px}
h2{font-size:1.15rem;margin:0 0 10px}
p{margin:0 0 12px;white-space:pre-wrap;overflow-wrap:anywhere}
.bar{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:16px;color:var(--muted);font-size:.875rem}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:16px}
.frame{display:block;width:100%;max-height:68vh;background:#000;border-radius:10px;margin-bottom:14px;object-fit:contain}
.line{margin:0 0 8px;overflow-wrap:anywhere}.speaker{font-weight:600;margin-right:.5em}
.actions{display:grid;gap:10px}
button{font:inherit;color:inherit;cursor:pointer;border-radius:10px;border:1px solid var(--line);background:var(--surface);padding:11px 14px;text-align:left;min-height:44px;overflow-wrap:anywhere}
button:hover:not(:disabled){border-color:var(--accent)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button:disabled{cursor:not-allowed;opacity:.6}
button.primary{background:var(--accent);color:var(--on-accent);border-color:var(--accent);font-weight:600;text-align:center}
button.quiet{min-height:36px;padding:6px 12px;font-size:.875rem;text-align:center}
.hint{display:block;font-size:.8125rem;color:var(--muted)}
.row{display:flex;flex-wrap:wrap;gap:8px}
.timer{height:6px;border-radius:3px;background:var(--line);overflow:hidden;margin-bottom:12px}
.timer i{display:block;height:100%;background:var(--accent);transition:width .1s linear}
.badge{display:inline-block;font-size:.8125rem;font-weight:600;color:var(--good);margin-bottom:6px}
.group{margin:16px 0 6px;font-weight:600;font-size:.875rem;color:var(--muted)}
.nodes{display:grid;gap:6px}
.values{display:grid;grid-template-columns:1fr auto;gap:2px 12px;font-size:.875rem;margin:0}
.values dt{color:var(--muted)}.values dd{margin:0;font-variant-numeric:tabular-nums}
"""

PLAYER_ENGINE_JS = r"""
var StoryEngine = (function () {
  function isNumber(value) { return typeof value === 'number' && isFinite(value); }
  function compare(actual, op, expected) {
    if (typeof actual === 'boolean' || typeof expected === 'boolean') {
      if (typeof actual !== 'boolean' || typeof expected !== 'boolean') return false;
      return op === 'eq' ? actual === expected : op === 'ne' ? actual !== expected : false;
    }
    if (!isNumber(actual) || !isNumber(expected)) return false;
    switch (op) {
      case 'eq': return actual === expected;
      case 'ne': return actual !== expected;
      case 'gt': return actual > expected;
      case 'gte': return actual >= expected;
      case 'lt': return actual < expected;
      case 'lte': return actual <= expected;
      default: return false;
    }
  }
  function evaluate(condition, values) {
    if (!condition) return true;
    if (condition.all) return condition.all.every(function (item) { return evaluate(item, values); });
    if (condition.any) return condition.any.some(function (item) { return evaluate(item, values); });
    return values.has(condition['var']) && compare(values.get(condition['var']), condition.op, condition.value);
  }
  function clamp(value, variable) {
    if (variable.min !== null && variable.min !== undefined) value = Math.max(value, variable.min);
    if (variable.max !== null && variable.max !== undefined) value = Math.min(value, variable.max);
    return value;
  }
  function initialValues(variables) {
    var values = new Map();
    variables.forEach(function (variable) {
      values.set(variable.id, variable.kind === 'flag' ? variable.initial === true : clamp(Number(variable.initial) || 0, variable));
    });
    return values;
  }
  function applyEffects(effects, values, definitions) {
    var result = new Map(values);
    (effects || []).forEach(function (effect) {
      var variable = definitions.get(effect['var']);
      if (!variable) return;
      if (variable.kind === 'flag') {
        if (effect.op === 'set' && typeof effect.value === 'boolean') result.set(effect['var'], effect.value);
      } else if (isNumber(effect.value)) {
        var base = effect.op === 'add' ? (result.has(effect['var']) ? result.get(effect['var']) : 0) : 0;
        result.set(effect['var'], clamp(Math.round((base + effect.value) * 1e6) / 1e6, variable));
      }
    });
    return result;
  }
  /* Everything the viewer can see after a segment, gated choices included, plus which way it resolves. */
  function nextStep(segment, values, known) {
    if (segment.kind === 'ending') return { kind: 'ending', options: [] };
    var routes = segment.routes || [];
    for (var i = 0; i < routes.length; i++) {
      if (known(routes[i].target) && evaluate(routes[i].condition, values)) return { kind: 'route', route: routes[i], options: [] };
    }
    var options = [];
    (segment.choices || []).forEach(function (choice) {
      if (!known(choice.target)) return;
      var open = evaluate(choice.condition, values);
      if (open || choice.when_locked !== 'hide') options.push({ choice: choice, locked: !open });
    });
    var anyOpen = options.some(function (option) { return !option.locked; });
    return { kind: anyOpen ? 'choices' : 'stuck', options: options };
  }
  /* A timed-out viewer gets the default, or the first open choice when the default is locked. */
  function timedChoice(segment, options) {
    var open = options.filter(function (option) { return !option.locked; });
    var wanted = segment.timer && segment.timer.default_choice;
    var match = open.filter(function (option) { return option.choice.id === wanted; })[0];
    return (match || open[0] || { choice: null }).choice;
  }
  return { compare: compare, evaluate: evaluate, initialValues: initialValues, applyEffects: applyEffects, nextStep: nextStep, timedChoice: timedChoice };
})();
"""

PLAYER_UI_JS = r"""
(function () {
  'use strict';
  function readJson(id) { return JSON.parse(document.getElementById(id).textContent); }
  var story = readJson('story-data');
  var text = readJson('story-chrome');
  var app = document.getElementById('app');
  var segments = new Map(story.segments.map(function (item) { return [item.id, item]; }));
  var definitions = new Map(story.variables.map(function (item) { return [item.id, item]; }));
  var known = function (id) { return segments.has(id); };
  var endingsTotal = story.segments.filter(function (item) { return item.kind === 'ending'; }).length;
  var storageKey = 'interactive-story:' + story.fingerprint;
  var timer = null;
  var blobUrls = new Map();

  var progress = { played: new Map(), unlocked: new Map(), endings: new Set(), current: null };

  /* Private windows, blocked storage and file:// pages can all throw here; the story must still play. */
  function saveProgress() {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify({
        played: Array.from(progress.played), unlocked: Array.from(progress.unlocked), endings: Array.from(progress.endings),
        current: progress.current ? { id: progress.current.id, values: Array.from(progress.current.values) } : null
      }));
    } catch (error) { /* progress just is not kept */ }
  }
  function loadProgress() {
    var saved = null;
    try { saved = JSON.parse(window.localStorage.getItem(storageKey) || 'null'); } catch (error) { saved = null; }
    if (!saved || typeof saved !== 'object') return;
    function rows(list) { return Array.isArray(list) ? list.filter(function (row) { return Array.isArray(row) && known(row[0]); }) : []; }
    rows(saved.played).forEach(function (row) { progress.played.set(row[0], cleanValues(row[1])); });
    rows(saved.unlocked).forEach(function (row) { progress.unlocked.set(row[0], cleanValues(row[1])); });
    (Array.isArray(saved.endings) ? saved.endings : []).forEach(function (id) { if (known(id)) progress.endings.add(id); });
    if (saved.current && known(saved.current.id)) progress.current = { id: saved.current.id, values: valueMap(cleanValues(saved.current.values)) };
  }
  /* Saved values are outside input: only known variables of the right type get back in. */
  function cleanValues(pairs) {
    var result = [];
    (Array.isArray(pairs) ? pairs : []).forEach(function (pair) {
      if (!Array.isArray(pair)) return;
      var variable = definitions.get(pair[0]);
      if (!variable) return;
      var fine = variable.kind === 'flag' ? typeof pair[1] === 'boolean' : (typeof pair[1] === 'number' && isFinite(pair[1]));
      if (fine) result.push([pair[0], pair[1]]);
    });
    return result;
  }
  function valueMap(pairs) {
    var values = StoryEngine.initialValues(story.variables);
    pairs.forEach(function (pair) { values.set(pair[0], pair[1]); });
    return values;
  }

  function node(tag, className, content) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    /* textContent only: story text never becomes markup. */
    if (content !== undefined && content !== null) element.textContent = content;
    return element;
  }
  function button(label, onClick, className) {
    var element = node('button', className || '', label);
    element.type = 'button';
    element.addEventListener('click', onClick);
    return element;
  }
  function clearTimer() { if (timer) { window.clearInterval(timer); timer = null; } }
  function clearApp() {
    clearTimer();
    app.querySelectorAll('video').forEach(function (video) { video.pause(); video.removeAttribute('src'); video.load(); });
    while (app.firstChild) app.removeChild(app.firstChild);
    window.scrollTo(0, 0);
  }

  /* A long data: URL stalls some browsers' media loaders; a blob: URL of the same bytes does not. */
  function mediaSource(src) {
    if (src.indexOf('data:video/') !== 0) return src;
    if (blobUrls.has(src)) return blobUrls.get(src);
    var comma = src.indexOf(',');
    var bytes = window.atob(src.slice(comma + 1));
    var buffer = new Uint8Array(bytes.length);
    for (var i = 0; i < bytes.length; i++) buffer[i] = bytes.charCodeAt(i);
    var url = URL.createObjectURL(new Blob([buffer], { type: src.slice(5, src.indexOf(';')) }));
    blobUrls.set(src, url);
    return url;
  }

  function showHome() {
    clearApp();
    var card = node('section', 'card');
    card.appendChild(node('h1', '', story.title || text.map));
    if (story.synopsis) card.appendChild(node('p', '', story.synopsis));
    var row = node('div', 'row');
    if (progress.current) row.appendChild(button(text.resume, function () { enter(progress.current.id, progress.current.values); }, 'primary'));
    row.appendChild(button(progress.current ? text.restart : text.start, restart, progress.current ? '' : 'primary'));
    if (progress.played.size) row.appendChild(button(text.map, showMap));
    card.appendChild(row);
    app.appendChild(card);
  }
  function restart() { enter(story.start, StoryEngine.initialValues(story.variables)); }

  function enter(id, values) {
    var segment = segments.get(id);
    if (!segment) { showHome(); return; }
    clearApp();
    var pairs = Array.from(values);
    progress.played.set(id, pairs);
    progress.unlocked.delete(id);
    if (segment.kind === 'ending') progress.endings.add(id);
    progress.current = segment.kind === 'ending' ? null : { id: id, values: values };
    saveProgress();

    var bar = node('div', 'bar');
    bar.appendChild(node('span', '', text.endings + ' ' + progress.endings.size + '/' + endingsTotal));
    bar.appendChild(button(text.map, showMap, 'quiet'));
    app.appendChild(bar);

    var card = node('section', 'card');
    var actions = node('div', 'actions');
    var shown = false;
    function reveal(auto) {
      if (shown) return;
      shown = true;
      showActions(segment, values, actions, auto);
    }
    var hasPlayingVideo = false;
    if (segment.media && segment.media.kind === 'image') {
      var image = node('img', 'frame');
      image.alt = segment.title || '';
      image.addEventListener('error', function () { image.remove(); });
      image.src = mediaSource(segment.media.src);
      card.appendChild(image);
    } else if (segment.media && segment.media.kind === 'video') {
      hasPlayingVideo = true;
      var video = node('video', 'frame');
      video.controls = true;
      video.playsInline = true;
      video.addEventListener('ended', function () { reveal(true); });
      /* A missing file falls back to the text card, never to a dead screen. */
      video.addEventListener('error', function () { video.remove(); skip.remove(); reveal(false); });
      video.src = mediaSource(segment.media.src);
      card.appendChild(video);
      var playing = video.play();
      if (playing && playing.catch) playing.catch(function () { /* the viewer can press play */ });
      var skip = button(text.skip, function () { video.pause(); skip.remove(); reveal(false); }, 'quiet');
      actions.appendChild(skip);
    }
    if (segment.kind === 'ending') card.appendChild(node('span', 'badge', text.ending + (segment.ending_label ? ' · ' + segment.ending_label : '')));
    if (segment.title) card.appendChild(node('h2', '', segment.title));
    if (segment.narration) card.appendChild(node('p', '', segment.narration));
    segment.dialogue.forEach(function (line) {
      var row = node('p', 'line');
      if (line.speaker) row.appendChild(node('span', 'speaker', line.speaker));
      row.appendChild(document.createTextNode(line.text));
      card.appendChild(row);
    });
    app.appendChild(card);
    app.appendChild(actions);
    if (!hasPlayingVideo) reveal(false);
  }

  function showActions(segment, values, holder, auto) {
    var outcome = StoryEngine.nextStep(segment, values, known);
    while (holder.firstChild) holder.removeChild(holder.firstChild);
    if (outcome.kind === 'ending') {
      var endRow = node('div', 'row');
      endRow.appendChild(button(text.restart, restart, 'primary'));
      endRow.appendChild(button(text.map, showMap));
      holder.appendChild(endRow);
      return;
    }
    if (outcome.kind === 'route') {
      if (auto) { enter(outcome.route.target, values); return; }
      holder.appendChild(button(text['continue'], function () { enter(outcome.route.target, values); }, 'primary'));
      return;
    }
    if (outcome.kind === 'stuck') holder.appendChild(node('p', 'hint', text.stuck));
    outcome.options.forEach(function (option) {
      if (option.locked) return;
      var after = StoryEngine.applyEffects(option.choice.effects, values, definitions);
      if (!progress.played.has(option.choice.target) && !progress.unlocked.has(option.choice.target)) {
        progress.unlocked.set(option.choice.target, Array.from(after));
      }
    });
    saveProgress();
    if (outcome.kind === 'choices' && segment.timer) startTimer(segment, values, outcome.options, holder);
    outcome.options.forEach(function (option) {
      var item = button(option.choice.text, function () { take(option.choice, values); });
      if (option.locked) {
        item.disabled = true;
        item.appendChild(node('span', 'hint', option.choice.locked_hint || text.locked));
      }
      holder.appendChild(item);
    });
    if (outcome.kind === 'stuck') holder.appendChild(button(text.restart, restart, 'primary'));
  }

  function take(choice, values) { enter(choice.target, StoryEngine.applyEffects(choice.effects, values, definitions)); }

  function startTimer(segment, values, options, holder) {
    var total = segment.timer.seconds * 1000;
    var deadline = Date.now() + total;
    var track = node('div', 'timer');
    var fill = node('i');
    fill.style.width = '100%';
    track.appendChild(fill);
    holder.appendChild(track);
    timer = window.setInterval(function () {
      var left = deadline - Date.now();
      fill.style.width = Math.max(0, left / total * 100) + '%';
      if (left <= 0) {
        clearTimer();
        var picked = StoryEngine.timedChoice(segment, options);
        if (picked) take(picked, values);
      }
    }, 100);
  }

  function group(card, title, items, handler) {
    card.appendChild(node('div', 'group', title + ' ' + items.length));
    var list = node('div', 'nodes');
    items.forEach(function (segment) {
      var label = segment.title || segment.id;
      if (handler) list.appendChild(button(label, function () { handler(segment); }));
    });
    if (handler) card.appendChild(list);
  }

  function showMap() {
    clearApp();
    var head = node('div', 'bar');
    head.appendChild(node('span', '', text.endings + ' ' + progress.endings.size + '/' + endingsTotal));
    head.appendChild(button(text.close, function () { if (progress.current) enter(progress.current.id, progress.current.values); else showHome(); }, 'quiet'));
    app.appendChild(head);
    var card = node('section', 'card');
    card.appendChild(node('h2', '', text.map));
    card.appendChild(node('p', 'hint', text.replay));
    var played = story.segments.filter(function (item) { return progress.played.has(item.id); });
    var unlocked = story.segments.filter(function (item) { return !progress.played.has(item.id) && progress.unlocked.has(item.id); });
    var unexplored = story.segments.length - played.length - unlocked.length;
    group(card, text.played, played, function (segment) { enter(segment.id, valueMap(progress.played.get(segment.id))); });
    group(card, text.unlocked, unlocked, function (segment) { enter(segment.id, valueMap(progress.unlocked.get(segment.id))); });
    card.appendChild(node('div', 'group', text.unexplored + ' ' + unexplored));
    if (unexplored) card.appendChild(node('p', 'hint', text.unknown));
    app.appendChild(card);
    if (progress.current && story.variables.length) {
      var box = node('section', 'card');
      box.appendChild(node('h2', '', text.progress));
      var list = node('dl', 'values');
      story.variables.forEach(function (variable) {
        var value = progress.current.values.get(variable.id);
        list.appendChild(node('dt', '', variable.label || variable.id));
        list.appendChild(node('dd', '', typeof value === 'boolean' ? (value ? text.onTrue : text.onFalse) : String(value)));
      });
      box.appendChild(list);
      app.appendChild(box);
    }
    var row = node('div', 'row');
    row.appendChild(button(text.restart, restart, 'primary'));
    row.appendChild(button(text.reset, function () {
      progress = { played: new Map(), unlocked: new Map(), endings: new Set(), current: null };
      try { window.localStorage.removeItem(storageKey); } catch (error) { /* nothing was kept */ }
      showHome();
    }));
    app.appendChild(row);
  }

  loadProgress();
  showHome();
})();
"""


__all__ = [
    "Condition", "Domain", "Effect", "Flow", "MAX_GRAPH_JSON_BYTES", "PLAYER_ENGINE_JS", "PLAYER_TEXT", "SAFE_MEDIA_PATTERN",
    "StoryGraph", "StoryInputError", "StoryPlanDraft", "analyze_paths", "analyze_story", "apply_effects", "can_be_true",
    "compare", "decision_seconds", "empty_stats", "evaluate", "flow_values", "format_errors", "initial_values", "media_urls",
    "parse_graph", "plan_problems", "player_story", "reading_seconds", "reassign_edge_ids", "record_playtest",
    "render_player_html", "route_key", "script_json", "segment_seconds", "stats_view", "step", "validate_graph",
]
