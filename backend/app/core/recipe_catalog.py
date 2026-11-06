"""General prompt recipes, kept as data in ``app/data/recipes``: read, checked, and filled in with a person's inputs.

Camera moves have their own composer in ``camera_recipes``; these are whole-asset briefs
(a key scene, a product image, a score). Rendering is plain text substitution and calls
no model, so listing and rendering are free; what happens to the prompt afterwards goes
through the same paid paths as any other.

Prompt syntax: ``{{name}}`` is an input; ``[[ … ]]`` is dropped whole when an input inside it is empty.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

RECIPES_DIR = Path(__file__).resolve().parents[1] / "data" / "recipes"

Category = Literal["short_drama", "ecommerce_image", "social_image", "general_image", "general_video", "general_audio"]
OutputType = Literal["image", "video", "audio"]

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
_OPTIONAL = re.compile(r"\[\[(.*?)\]\]", re.S)
_MAX_INPUT = 2000


class RecipeCatalogError(ValueError):
    """A recipe file on disk is wrong; names the file and the recipe so it can be fixed."""


class RecipeInputError(ValueError):
    """The inputs given for a render are not usable."""


class RecipeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)
    label: str = Field(min_length=1, max_length=120)
    type: Literal["text", "choice", "number"] = "text"
    required: bool = False
    default: str = ""
    choices: list[str] = Field(default_factory=list)
    max_length: int = Field(default=500, ge=1, le=_MAX_INPUT)
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def consistent(self) -> "RecipeInput":
        if self.type == "choice" and not self.choices:
            raise ValueError(f"选项型输入 {self.name} 需要 choices")
        if self.type != "choice" and self.choices:
            raise ValueError(f"输入 {self.name} 不是选项型，不能有 choices")
        if self.default and self.type == "choice" and self.default not in self.choices:
            raise ValueError(f"输入 {self.name} 的默认值不在 choices 里")
        if self.default and self.type == "number":
            self.check_number(self.default)
        if self.type != "number" and (self.minimum is not None or self.maximum is not None):
            raise ValueError(f"输入 {self.name} 不是数字型，不能有范围")
        return self

    def check_number(self, value: str) -> None:
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError(f"「{self.label}」要填数字") from exc
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"「{self.label}」要填数字")
        if (self.minimum is not None and number < self.minimum) or (self.maximum is not None and number > self.maximum):
            raise ValueError(f"「{self.label}」要在 {self.minimum:g} 到 {self.maximum:g} 之间")


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$", max_length=60)
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=200)
    output_type: OutputType
    inputs: list[RecipeInput] = Field(min_length=1, max_length=12)
    prompt: str = Field(min_length=20, max_length=4000)
    negative: str = Field(default="", max_length=500)
    params: dict[str, Any] = Field(default_factory=dict)
    category: Category = "general_image"
    category_label: str = ""

    @model_validator(mode="after")
    def placeholders_match_inputs(self) -> "Recipe":
        declared = [item.name for item in self.inputs]
        if len(declared) != len(set(declared)):
            raise ValueError("输入名重复")
        used = set(_PLACEHOLDER.findall(self.prompt))
        unknown = used - set(declared)
        if unknown:
            raise ValueError(f"提示词用了未声明的输入：{'、'.join(sorted(unknown))}")
        unused = set(declared) - used
        if unused:
            raise ValueError(f"声明了但提示词没用的输入：{'、'.join(sorted(unused))}")
        always = _PLACEHOLDER.findall(_OPTIONAL.sub("", self.prompt))
        for item in self.inputs:
            if not item.required and not item.default and item.name in always:
                raise ValueError(f"可选输入 {item.name} 没有默认值，必须放进 [[ ]] 里")
        if "{" in _PLACEHOLDER.sub("", self.prompt) or "}" in _PLACEHOLDER.sub("", self.prompt):
            raise ValueError("提示词里有写坏的占位符")
        return self


class RecipeFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    label: str = Field(min_length=1, max_length=40)
    recipes: list[Recipe] = Field(min_length=1)


class RecipeCatalog:
    def __init__(self, recipes: list[Recipe], labels: Mapping[str, str]) -> None:
        self.recipes = recipes
        self.labels = dict(labels)
        self._by_id = {recipe.id: recipe for recipe in recipes}

    def get(self, recipe_id: str) -> Recipe:
        recipe = self._by_id.get(recipe_id)
        if recipe is None:
            raise LookupError(f"没有叫 {recipe_id} 的配方")
        return recipe

    def search(self, *, category: str = "", output_type: str = "", query: str = "") -> list[Recipe]:
        words = query.strip().lower()
        return [
            recipe for recipe in self.recipes
            if (not category or recipe.category == category)
            and (not output_type or recipe.output_type == output_type)
            and (not words or words in f"{recipe.id} {recipe.name} {recipe.description}".lower())
        ]

    def describe(self, *, category: str = "", output_type: str = "", query: str = "") -> dict[str, Any]:
        found = self.search(category=category, output_type=output_type, query=query)
        return {
            "categories": [{"id": key, "label": label} for key, label in self.labels.items()],
            "recipes": [describe_recipe(recipe) for recipe in found],
            "total": len(found),
        }


def describe_recipe(recipe: Recipe) -> dict[str, Any]:
    return {
        "id": recipe.id, "name": recipe.name, "description": recipe.description, "category": recipe.category,
        "category_label": recipe.category_label, "output_type": recipe.output_type,
        "inputs": [item.model_dump(exclude_none=True) for item in recipe.inputs], "params": dict(recipe.params),
    }


def load_catalog(directory: Path = RECIPES_DIR) -> RecipeCatalog:
    """Read and check every file; a wrong one fails here, naming itself, not at someone's render."""
    recipes: list[Recipe] = []
    labels: dict[str, str] = {}
    seen: dict[str, str] = {}
    files = sorted(directory.glob("*.json"))
    if not files:
        raise RecipeCatalogError(f"{directory} 里没有配方文件")
    for path in files:
        try:
            parsed = RecipeFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RecipeCatalogError(f"{path.name}: {exc}") from exc
        if parsed.category in labels:
            raise RecipeCatalogError(f"{path.name}: 类别 {parsed.category} 已在别的文件里定义")
        labels[parsed.category] = parsed.label
        for recipe in parsed.recipes:
            if recipe.id in seen:
                raise RecipeCatalogError(f"{path.name}: 配方 {recipe.id} 与 {seen[recipe.id]} 重复")
            seen[recipe.id] = path.name
            recipes.append(recipe.model_copy(update={"category": parsed.category, "category_label": parsed.label}))
    return RecipeCatalog(recipes, labels)


@lru_cache(maxsize=1)
def catalog() -> RecipeCatalog:
    return load_catalog()


def _values(recipe: Recipe, given: Mapping[str, Any]) -> dict[str, str]:
    declared = {item.name: item for item in recipe.inputs}
    unknown = [name for name in given if name not in declared]
    if unknown:
        raise RecipeInputError(f"配方 {recipe.id} 没有这些输入：{'、'.join(unknown)}")
    values: dict[str, str] = {}
    for item in recipe.inputs:
        raw = given.get(item.name)
        text = " ".join(str(raw).split()) if raw is not None else ""
        text = text or item.default
        if item.required and not text:
            raise RecipeInputError(f"缺少「{item.label}」")
        if len(text) > item.max_length:
            raise RecipeInputError(f"「{item.label}」最长 {item.max_length} 个字符")
        if text and item.type == "choice" and text not in item.choices:
            raise RecipeInputError(f"「{item.label}」只能是：{'、'.join(item.choices)}")
        if text and item.type == "number":
            try:
                item.check_number(text)
            except ValueError as exc:
                raise RecipeInputError(str(exc)) from exc
        values[item.name] = text
    return values


def render(recipe_id: str, inputs: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The filled prompt. Substitution is one pass, so text a person typed is never read as syntax."""
    recipe = catalog().get(recipe_id)
    values = _values(recipe, inputs or {})

    def optional(match: re.Match[str]) -> str:
        names = _PLACEHOLDER.findall(match.group(1))
        return match.group(1) if all(values.get(name) for name in names) else ""

    template = _OPTIONAL.sub(optional, recipe.prompt)
    prompt = _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
    return {
        "recipe_id": recipe.id, "name": recipe.name, "category": recipe.category, "output_type": recipe.output_type,
        "prompt": prompt.strip(), "negative": recipe.negative, "params": dict(recipe.params), "inputs": values,
    }
