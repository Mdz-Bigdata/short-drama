#!/usr/bin/env python3
"""Add motions from the Quaternius Universal Animation Library to the desk's built-in figure.

The figure the 3D director desk ships (public/models/director-desk/humanoid-v1.glb) is a curated
derivative of the library's mannequin: the same skeleton without its twelve fingertip and toe-tip
bones, ten motions, anatomical node names. This tool copies more motions onto that skeleton and
writes humanoid-v2.glb beside it. Nothing about the mesh, the skin or the first ten motions changes.

    python3 scripts/build-humanoid-motions.py UAL1_Standard.glb UAL2_Standard.glb

The two inputs are the free "Standard" files of Universal Animation Library 1 and 2 (CC0-1.0,
https://quaternius.com). They are not kept in this repository. Standard library only, no packages.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS = HERE.parent / "public" / "models" / "director-desk"
BASE = MODELS / "humanoid-v1.glb"
OUT = MODELS / "humanoid-v2.glb"

# (library file, its animation, the name the figure file gives it). The order is the order they are
# appended in, which is the `index` the clip table in humanoidClips.ts counts from 10.
MOTIONS: list[tuple[str, str, str]] = [
    ("UAL1_Standard.glb", "Sword_Idle", "持剑戒备"),
    ("UAL1_Standard.glb", "Sword_Attack", "挥剑劈砍"),
    ("UAL2_Standard.glb", "Sword_Block", "持剑格挡"),
    ("UAL2_Standard.glb", "Sword_Dash", "持剑突刺"),
    ("UAL2_Standard.glb", "Sword_Regular_C", "回身重斩"),
    ("UAL2_Standard.glb", "Sword_Regular_Combo", "三连斩"),
    ("UAL2_Standard.glb", "Sword_Heavy_Combo", "重击连招"),
    ("UAL1_Standard.glb", "Punch_Jab", "刺拳"),
    ("UAL1_Standard.glb", "Punch_Cross", "直拳"),
    ("UAL2_Standard.glb", "Melee_Hook", "勾拳"),
    ("UAL1_Standard.glb", "Hit_Chest", "胸口受击"),
    ("UAL1_Standard.glb", "Hit_Head", "头部受击"),
    ("UAL2_Standard.glb", "Hit_Knockback", "被击退"),
    ("UAL1_Standard.glb", "Death01", "中招倒地"),
    ("UAL2_Standard.glb", "LayToIdle", "倒地起身"),
    ("UAL1_Standard.glb", "Roll", "翻滚"),
    ("UAL1_Standard.glb", "Jump_Start", "起跳"),
    ("UAL1_Standard.glb", "Jump_Loop", "腾空"),
    ("UAL1_Standard.glb", "Jump_Land", "落地"),
    ("UAL2_Standard.glb", "NinjaJump_Start", "轻功起跳"),
    ("UAL2_Standard.glb", "NinjaJump_Idle_Loop", "轻功腾空"),
    ("UAL2_Standard.glb", "NinjaJump_Land", "轻功落地"),
    ("UAL1_Standard.glb", "Sprint_Loop", "冲刺"),
    ("UAL2_Standard.glb", "Idle_FoldArms_Loop", "抱臂而立"),
]

FLOAT = 5126
WIDTH = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}
REST = {"translation": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0, 1.0), "scale": (1.0, 1.0, 1.0)}
# A channel that never leaves the rest pose says nothing: the figure already stands that way.
STILL = 1e-5


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, version, _ = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2:
        raise SystemExit(f"{path.name}: not a binary glTF 2.0 file")
    json_length, json_kind = struct.unpack_from("<II", data, 12)
    if json_kind != 0x4E4F534A:
        raise SystemExit(f"{path.name}: the first chunk is not JSON")
    document = json.loads(data[20:20 + json_length])
    offset = 20 + json_length
    bin_length, bin_kind = struct.unpack_from("<II", data, offset)
    if bin_kind != 0x004E4942:
        raise SystemExit(f"{path.name}: the second chunk is not binary")
    return document, data[offset + 8:offset + 8 + bin_length]


def write_glb(path: Path, document: dict, binary: bytes) -> None:
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    path.write_bytes(b"".join([
        struct.pack("<4sII", b"glTF", 2, total),
        struct.pack("<II", len(text), 0x4E4F534A), text,
        struct.pack("<II", len(binary), 0x004E4942), binary,
    ]))


def floats(document: dict, binary: bytes, accessor_index: int) -> tuple[list[float], int]:
    """An accessor's numbers and how many go to one key."""
    accessor = document["accessors"][accessor_index]
    if accessor["componentType"] != FLOAT or "sparse" in accessor:
        raise SystemExit(f"accessor {accessor_index}: only plain float accessors are read")
    view = document["bufferViews"][accessor["bufferView"]]
    width = WIDTH[accessor["type"]]
    if view.get("byteStride", width * 4) != width * 4:
        raise SystemExit(f"accessor {accessor_index}: interleaved data is not read")
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    return list(struct.unpack_from(f"<{accessor['count'] * width}f", binary, start)), width


def bone_map(base: dict, source: dict) -> dict[int, int]:
    """Library node → figure node, found by walking the two trees side by side.

    The figure has the library's skeleton minus the `*_leaf` end bones, in the same order, so the
    n-th child that is not a leaf is the n-th child here. A rest position that disagrees means the
    files are not the ones this tool was written for.
    """
    mapping: dict[int, int] = {}

    def walk(theirs: int, ours: int) -> None:
        mapping[theirs] = ours
        a, b = source["nodes"][theirs], base["nodes"][ours]
        for key in ("translation", "rotation", "scale"):
            if any(abs(x - y) > 1e-4 for x, y in zip(a.get(key, REST[key]), b.get(key, REST[key]))):
                raise SystemExit(f"rest {key} of {a.get('name')} differs from {b.get('name')}")
        kept = [child for child in a.get("children", []) if not str(source["nodes"][child].get("name", "")).endswith(("_leaf_l", "_leaf_r"))]
        children = b.get("children", [])
        if len(kept) != len(children):
            raise SystemExit(f"{a.get('name')} has {len(kept)} children, {b.get('name')} has {len(children)}")
        for child, mine in zip(kept, children):
            walk(child, mine)

    walk(source["scenes"][0]["nodes"][0], base["scenes"][0]["nodes"][0])
    return mapping


class Writer:
    """Appends float accessors to the figure's document and buffer."""

    def __init__(self, document: dict, binary: bytes):
        self.document = document
        self.binary = bytearray(binary)
        self.binary += b"\0" * (-len(self.binary) % 4)

    def add(self, values: list[float], kind: str, bounds: bool = False) -> int:
        view = {"buffer": 0, "byteOffset": len(self.binary), "byteLength": len(values) * 4}
        self.binary += struct.pack(f"<{len(values)}f", *values)
        self.document["bufferViews"].append(view)
        accessor: dict = {"bufferView": len(self.document["bufferViews"]) - 1, "componentType": FLOAT, "count": len(values) // WIDTH[kind], "type": kind}
        if bounds:
            accessor["min"], accessor["max"] = [min(values)], [max(values)]
        self.document["accessors"].append(accessor)
        return len(self.document["accessors"]) - 1


def copy_motion(writer: Writer, source: dict, binary: bytes, mapping: dict[int, int], animation: dict, name: str) -> dict:
    times: dict[int, int] = {}
    ends: dict[tuple[float, float], int] = {}
    samplers: list[dict] = []
    channels: list[dict] = []
    for channel in animation["channels"]:
        target = channel["target"]
        node = mapping.get(target.get("node", -1))
        if node is None:
            continue  # a fingertip or toe-tip bone the figure does not have
        sampler = animation["samplers"][channel["sampler"]]
        if sampler.get("interpolation", "LINEAR") != "LINEAR":
            raise SystemExit(f"{name}: {sampler.get('interpolation')} keys are not copied")
        values, width = floats(source, binary, sampler["output"])
        stamps, _ = floats(source, binary, sampler["input"])
        first = values[:width]
        constant = all(abs(values[index] - first[index % width]) <= STILL for index in range(len(values)))
        rest = writer.document["nodes"][node].get(target["path"], REST[target["path"]])
        if constant and all(abs(a - b) <= STILL for a, b in zip(first, rest)):
            continue
        if constant:
            # Held away from rest for the whole motion: two keys say it as well as ninety.
            span = (stamps[0], stamps[-1])
            if span not in ends:
                ends[span] = writer.add(list(span), "SCALAR", bounds=True)
            time_accessor, output = ends[span], writer.add(first + first, source["accessors"][sampler["output"]]["type"])
        else:
            if sampler["input"] not in times:
                times[sampler["input"]] = writer.add(stamps, "SCALAR", bounds=True)
            time_accessor, output = times[sampler["input"]], writer.add(values, source["accessors"][sampler["output"]]["type"])
        samplers.append({"input": time_accessor, "output": output, "interpolation": "LINEAR"})
        channels.append({"sampler": len(samplers) - 1, "target": {"node": node, "path": target["path"]}})
    return {"name": name, "samplers": samplers, "channels": channels}


def same_channels(base: dict, base_bin: bytes, source: dict, source_bin: bytes, mapping: dict[int, int], ours: str, theirs: str) -> tuple[int, int]:
    """How many channels of a motion the figure already has are number for number the library's own.

    Not all of them are: the figure was cut from an earlier release of the library, which has since
    straightened the chest in every motion and reworked the legs of the walk. Bones matched wrongly
    would agree on next to nothing.
    """
    mine = next(item for item in base["animations"] if item.get("name") == ours)
    other = next(item for item in source["animations"] if item.get("name") == theirs)
    have = {(channel["target"]["node"], channel["target"]["path"]): floats(base, base_bin, mine["samplers"][channel["sampler"]]["output"])[0] for channel in mine["channels"]}
    same = total = 0
    for channel in other["channels"]:
        node = mapping.get(channel["target"]["node"])
        if node is None:
            continue
        values = floats(source, source_bin, other["samplers"][channel["sampler"]]["output"])[0]
        kept = have[(node, channel["target"]["path"])]
        total += 1
        same += len(kept) == len(values) and all(abs(a - b) <= 1e-4 for a, b in zip(values, kept))
    return same, total


def main(arguments: list[str]) -> None:
    libraries = {Path(item).name: Path(item) for item in arguments}
    missing = sorted({library for library, _, _ in MOTIONS} - set(libraries))
    if missing:
        raise SystemExit(f"usage: build-humanoid-motions.py UAL1_Standard.glb UAL2_Standard.glb (missing: {', '.join(missing)})")
    base, base_bin = read_glb(BASE)
    writer = Writer(base, base_bin)
    loaded: dict[str, tuple[dict, bytes, dict[int, int]]] = {}
    for library, path in libraries.items():
        source, source_bin = read_glb(path)
        loaded[library] = (source, source_bin, bone_map(base, source))
    # The figure's motions are the library's: if the bones were matched wrong, this is where it shows.
    source, source_bin, mapping = loaded["UAL1_Standard.glb"]
    for ours, theirs in (("站立待机", "Idle_Loop"), ("慢跑", "Jog_Fwd_Loop"), ("坐下", "Sitting_Enter")):
        same, total = same_channels(base, base_bin, source, source_bin, mapping, ours, theirs)
        if same < total * 0.9:
            raise SystemExit(f"{ours} agrees with {theirs} on only {same} of {total} channels: the bones do not line up")
        print(f"bones line up: {ours} = {theirs} on {same} of {total} channels")
    before = len(base["animations"])
    for library, theirs, name in MOTIONS:
        source, source_bin, mapping = loaded[library]
        animation = next((item for item in source["animations"] if item.get("name") == theirs), None)
        if animation is None:
            raise SystemExit(f"{library} has no motion called {theirs}")
        copied = copy_motion(writer, source, source_bin, mapping, animation, name)
        base["animations"].append(copied)
        duration = max(base["accessors"][sampler["input"]]["max"][0] for sampler in copied["samplers"])
        print(f"{len(base['animations']) - 1:3d}  {name}  {theirs}  {duration:.4f}s  {len(copied['channels'])} channels")
    base["asset"]["generator"] = "DirectorDesk motion library v1 + scripts/build-humanoid-motions.py"
    base["buffers"][0]["byteLength"] = len(writer.binary) + (-len(writer.binary) % 4)
    write_glb(OUT, base, bytes(writer.binary))
    written = OUT.read_bytes()
    print(f"{OUT.name}: {before} + {len(MOTIONS)} motions, {len(written):,} bytes, sha256 {hashlib.sha256(written).hexdigest()}")


if __name__ == "__main__":
    main(sys.argv[1:])
