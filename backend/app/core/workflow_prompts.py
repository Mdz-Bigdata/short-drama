"""Chinese production prompt contracts supplied for storyboard and video stages.

The long-form constants preserve the user-provided operating rules.  Runtime
helpers compile those rules into provider-ready, standalone batch prompts.
"""

from __future__ import annotations

from app.core import prompt_data



STORYBOARD_SCRIPT_PROMPT = prompt_data.text("agent_prompts", "storyboard_script_prompt")
VIDEO_STORYBOARD_PROMPT = prompt_data.text("agent_prompts", "video_storyboard_prompt")
