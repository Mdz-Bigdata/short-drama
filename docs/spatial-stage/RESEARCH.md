# Spatial Stage Research

## Overview

Two open-source 3D previs tools were reviewed as references for giving every scene of a short drama
one spatial truth — who stands where, what the set holds, where each camera is — so that character,
scene and spatial consistency stop depending on prose that every shot rewrites.

| Source | Reviewed commit | License | What it is |
|---|---|---|---|
| [storyai-3d-director-desk](https://github.com/jiguang132/storyai-3d-director-desk) | `8c8bd36` | MIT (code); its mannequin GLB is Sketchfab Standard | React + Three.js director desk: characters, props, look-at cameras, director / camera view, pose presets, project JSON, host bridge |
| [CoStage](https://github.com/cs68614-hash/costage) | `fa1b7fa` | none observed | Three.js stage driven by semantic MCP operations: relative placement, facing pairs, formations, FOV framing, action-stage timeline |

## Problem Statement

Before this work the four spatial fields of every stage-4 storyboard panel were constants:

- `action_axis = "沿场景圣经指定轴线，人物不越180度轴线"`
- `eyeline = "说话人与聆听者视线方向、高度和出入画位置连续"`
- `blocking = "保持人物左右关系、视线匹配与关键道具位置，不越180度轴线"`
- `composition = "主体落在三分线，前中后景层次清楚…"`

Consequences, all observable in the pipeline:

- `parse_frame_positions` never found a position, so `frame_positions_in_screen_coordinates` was a
  permanent warning and every still / video prompt fell back to "按构图描述锁定站位与朝向".
- Nothing said *which* character is screen left. Shot / reverse-shot relied on the image model guessing
  the same answer nine times.
- The only 180-degree check (`continuity.plan_transition`) was fed by keyword sniffing on the shot
  description ("向右" → `left_to_right`).
- Two scenes in the same location shared no layout: a door or a desk could be anywhere.
- `schema/studio.py` already had a `DirectorWorld` (anchors / actors / cameras) but it is bound to the
  Studio project, and nothing in the eight-stage drama pipeline reads it.

## What the references contribute

**storyai-3d-director-desk** — a small, clear data model (flat objects with transforms, cameras as
`position + target + fov`), a director view beside a camera view, an aspect frame, 20 pose presets
over 25 rig controls, per-instance scene scoping for embedding in a host, and project JSON. It has no
notion of shot size, screen position, axis or framing checks.

**CoStage** — blocking expressed by meaning: `place_relative` against a camera, a character or the
world; `arrange_facing_pair`; `arrange_group` (line / grid / circle / arc plus a facing pass);
`orient_toward`; auto-placement from `visible height = 2·d·tan(fov/2)`; a timeline whose new action
stage must really change a character's position, rotation or pose; monotonic revisions. Its shot
sizes, over-the-shoulder setups, the 180-degree rule and every spatial verification (facing dot
product, frustum containment, overlap) exist only as instructions to an LLM, not as code.

## Gap both leave open

Neither computes what a storyboard needs: a camera *from* a shot size, where a character lands *in the
frame*, which side of the axis a camera is on, whether a cut jumps it, whether the subject is in frame
or hidden. Those are this project's own and are the point of the integration.

## Decisions

- One plan per scene, task-scoped, stored with the stage-4 assets. Shots name a camera on it; the
  four panel sentences are *measured*, not written.
- Deterministic planner (no model call): the same cast, location and table give the same marks.
- CoStage has no license: behavior is reimplemented clean-room from standard geometry, in a different
  convention (yaw in degrees, forward `+Z` like a three.js object; CoStage faces `+X`, radians).
  No code, skill prose or models are copied.
- storyai is MIT: concepts adapted with attribution; no files copied. Its mannequin is a Sketchfab
  Standard asset and is not used — stand-ins are procedural and limb-less, which is also what the
  project's white-model rules ask for (`backend/app/data/sd25_blockout_rules.md`).
- Both tools remain usable: a stage exports to either format and imports positions back by name.
