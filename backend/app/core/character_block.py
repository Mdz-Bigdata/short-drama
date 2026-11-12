# -*- coding: utf-8 -*-
"""How a character's block (the look written on a character card) is written.

Five rules, kept in ``app/data/prompt/character_block.json``: only what never changes, the most
telling features first, the costume pinned to one garment, one block per person, one voice for
the whole drama. The screenwriter's asset inventory and the stage-3 character designer both
read them from here, so the two can never ask for different things.
"""

from __future__ import annotations

from app.core import prompt_data

_DATA = "character_block"


def rules_line(*, authored: bool = False) -> str:
    """The rules as one numbered line.

    A finished screenplay's descriptions are the author's, so ``authored`` keeps only the last
    two rules (one block per person, one voice).
    """
    rules = prompt_data.words(_DATA, "rules")
    picked = rules[3:] if authored else rules
    return prompt_data.text(_DATA, "rules_line").format(
        rules="；".join(f"（{index}）{rule}" for index, rule in enumerate(picked, 1)),
    )


def designer_rules() -> str:
    """The rules as the stage-3 character designer reads them, after its own methodology."""
    return prompt_data.text(_DATA, "designer_heading") + "\n" + "\n".join(
        f"{index}. {rule}。" for index, rule in enumerate(prompt_data.words(_DATA, "rules"), 1)
    ) + "\n\n"


__all__ = ["designer_rules", "rules_line"]
