"""Recursive harnessing for the stage agents: a stage's own execution improves its prompt overlay.

The method is Harness² (google-research/harness2, Apache-2.0; Xu et al., arXiv:2610.14224), written
anew for this project's agents, whose execution is one model call rather than a tool loop:

* task-level recursion (``recursion``): propose edits to the overlay on two dimensions (how the agent
  works / what a practitioner knows), probe each by running the same stage call under it, and compose
  one overlay from the contrasts between those executions. No score or reference answer is involved;
* blind selection and reflection (``selection``): the produced outputs are compared with their
  origins hidden, and one transferable lesson is written only when an execution contrast supports it;
* harnessing-level recursion (``library``): the adopted overlay and its lesson are kept per kind of
  production and read by later proposers; the overlay that won its comparison is the one later
  projects of the kind run with, and the next study edits it in place.

Also from upstream, in this project's terms: the ``scripts`` component as a list of checks a machine
runs on every execution (``checks``); each kind of work's lens, yardstick and meaning of "correct"
(the ``works`` table of the wording file); a measure of whether refinement pays off, which here is a
bare execution standing in the blind comparison and an automatic rollback when it wins (``engine``,
``library.summarise``); and studies that resume after a restart (``app/service/harness_evolution.py``).

What is not carried over: the executor substrates (OpenCode, Codex), the benchmark adapters and their
judges, and two of the eight harness components (subagents, plugins), which a single model call has
nothing to attach to.
"""

from app.core.harness_recursion.engine import StepRecord, Work, step
from app.core.harness_recursion.harness import COMPONENTS, Harness

__all__ = ["COMPONENTS", "Harness", "StepRecord", "Work", "step"]
