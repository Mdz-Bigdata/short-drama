---
name: short-drama-canvas
description: Plan and run short-drama and video production on the app's node canvas through its MCP tools. Use when asked to make a clip, trailer, short drama or image set, or to continue a canvas workflow.
---

# Producing on the canvas

Every project has a node canvas. Each node makes one thing, and connections hand results on.

## Making something new

1. `list_projects` to find the project, or ask which one.
2. `plan_canvas_workflow` with the brief. This calls a text model, so it needs `confirm: true`. It writes a draft and does not change the canvas.
3. Show the person the steps. Change the plan if they want changes.
4. `apply_canvas_workflow` puts every step on the canvas in one change. Nothing runs yet.
5. `canvas_workflow_status` gives `runnable`. `quote_canvas_run` prices those nodes: tell the person the cost.
6. Only after they agree, `run_canvas_nodes` with `confirm: true`.

## After a failure

Call `canvas_workflow_status` again. `runnable` lists only the steps with no result, so running those does not repeat or re-bill finished steps. Say what failed and why before retrying.

## Rules

- Never pass `confirm: true` on a paid tool until the person has agreed to that cost.
- Video generation needs a reference: connect an image or a clip. There is no text-to-video.
- A step of kind `media` waits for the person to upload a file. Ask them to; you cannot do it for them.
- `list_canvas_tools` lists the one-step tools. Check what a tool accepts before planning it. Local tools are free; upscale and region erase there are signal processing, not generative repair.
- For small edits use `get_canvas` then `edit_canvas`, with all changes in one call.
