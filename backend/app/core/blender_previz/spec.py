# -*- coding: utf-8 -*-
"""Blender 预演规格：空间方案(StagePlan)交给 Blender 渲染前的中间格式。

坐标已经是 Blender 的 Z 轴向上(米)；朝向 yaw 0 = 面向 -Y。每个代理绑定一个资产身份，主要角色的颜色互不相同——
颜色是视频参考里"这一团是谁"的唯一线索。规则见 skills/shot-design-master/references/blender-previz-protocol.md。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Vec3 = tuple[float, float, float]
Shape = Literal["capsule", "box", "cylinder", "sphere", "cone"]
Interpolation = Literal["BEZIER", "LINEAR", "CONSTANT"]

MAX_FRAMES = 60 * 24 * 2       # 两分钟 @24fps：一场预演的上限
WORLD_LIMIT = 500.0
MAX_SET_BLOCKS = 400


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _inside(values) -> None:
    if any(not -WORLD_LIMIT <= float(v) <= WORLD_LIMIT for v in values):
        raise ValueError(f"坐标超出 ±{WORLD_LIMIT:g} 米")


class Key(_Model):
    frame: int = Field(ge=1, le=MAX_FRAMES)
    position: Vec3
    yaw_deg: float | None = None

    @field_validator("position")
    @classmethod
    def _bounded(cls, value: Vec3) -> Vec3:
        _inside(value)
        return value


class Binding(_Model):
    kind: Literal["actor", "extra", "prop", "product", "effect"]
    name: str = Field(min_length=1, max_length=120)
    asset_id: str = Field(default="", max_length=120)


class Proxy(_Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    binds: Binding
    shape: Shape = "capsule"
    size: Vec3
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    keys: list[Key] = Field(min_length=1, max_length=2000)
    hidden: list[tuple[int, int]] = Field(default_factory=list, max_length=200)
    lying: bool = False
    interpolation: Interpolation = "BEZIER"


class Block(_Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(default="", max_length=120)
    shape: Literal["box", "cylinder", "sphere", "cone", "wedge"] = "box"
    size: Vec3
    position: Vec3
    yaw_deg: float = 0.0
    color: str = Field(default="#b0b0b0", pattern=r"^#[0-9a-fA-F]{6}$")
    # 组合模型的一个部件：basis 是 3×3 旋转矩阵(按行)，position 写的是部件中心而不是底面中心。
    basis: list[float] = Field(default_factory=list, max_length=9)


class Floor(_Model):
    size: tuple[float, float] = (20.0, 20.0)
    color: str = Field(default="#6f7075", pattern=r"^#[0-9a-fA-F]{6}$")


class SetDressing(_Model):
    floor: Floor = Field(default_factory=Floor)
    blocks: list[Block] = Field(default_factory=list, max_length=MAX_SET_BLOCKS)


class Target(_Model):
    """摄影机看哪里：跟随代理(加偏移)，或走自己的关键帧路径。摄影机只管位置与速度，目标只管构图。"""
    proxy: str = ""
    offset: Vec3 = (0.0, 0.0, 0.0)
    keys: list[Key] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def _one(self) -> "Target":
        if bool(self.proxy) == bool(self.keys):
            raise ValueError("target 只能二选一：跟随代理 或 自己的路径")
        return self


class Handheld(_Model):
    """真实手持：低频身体摆动 + 小幅不规则微震；不是高频 wiggle。"""
    sway_cm: float = Field(default=1.5, ge=0, le=8)
    sway_hz: float = Field(default=0.45, ge=0.1, le=1.2)
    jitter_cm: float = Field(default=0.3, ge=0, le=1.5)
    seed: int = 7
    start: int = Field(default=1, ge=1, le=MAX_FRAMES)
    end: int = Field(default=1, ge=1, le=MAX_FRAMES)


class LensKey(_Model):
    frame: int = Field(ge=1, le=MAX_FRAMES)
    lens_mm: float = Field(ge=8, le=600)


class Camera(_Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    lens_mm: float = Field(default=35, ge=8, le=600)
    keys: list[Key] = Field(min_length=1, max_length=2000)
    lens_keys: list[LensKey] = Field(default_factory=list, max_length=400)
    target: Target
    handheld: Handheld | None = None
    interpolation: Interpolation = "BEZIER"


class Cut(_Model):
    """硬切是帧级合同：这一帧起换到 camera，没有过渡帧。label 是镜号。"""
    frame: int = Field(ge=1, le=MAX_FRAMES)
    camera: str
    label: str = Field(default="", max_length=40)


class Reserved(_Model):
    label: str = Field(min_length=1, max_length=40)
    start: int = Field(ge=1, le=MAX_FRAMES)
    end: int = Field(ge=1, le=MAX_FRAMES)


class BlockingSpec(_Model):
    title: str = Field(default="", max_length=200)
    fps: int = Field(default=24, ge=12, le=60)
    frames: int = Field(ge=1, le=MAX_FRAMES)
    resolution: tuple[int, int] = (1920, 1080)
    set: SetDressing = Field(default_factory=SetDressing)
    proxies: list[Proxy] = Field(default_factory=list, max_length=400)
    cameras: list[Camera] = Field(default_factory=list, max_length=200)
    cuts: list[Cut] = Field(default_factory=list, max_length=200)
    reserved: list[Reserved] = Field(default_factory=list, max_length=40)
    render_video: bool = True

    @model_validator(mode="after")
    def _consistent(self) -> "BlockingSpec":
        ids = [p.id for p in self.proxies]
        if len(set(ids)) != len(ids):
            raise ValueError("代理 id 重复")
        principals = [p.color.lower() for p in self.proxies if p.binds.kind != "extra"]
        if len(set(principals)) != len(principals):
            raise ValueError("两个主要代理用了同一种颜色：视频参考里分不清谁是谁")
        cams = {c.id for c in self.cameras}
        if len(cams) != len(self.cameras):
            raise ValueError("摄影机 id 重复")
        for cam in self.cameras:
            if cam.target.proxy and cam.target.proxy not in ids:
                raise ValueError(f"摄影机 {cam.id} 的目标代理 {cam.target.proxy} 不存在")
        frames = [cut.frame for cut in self.cuts]
        if len(set(frames)) != len(frames):
            raise ValueError("同一帧上有两个切点")
        for cut in self.cuts:
            if cut.camera not in cams:
                raise ValueError(f"切点用到的摄影机 {cut.camera} 不存在")
            if cut.frame > self.frames:
                raise ValueError(f"切点帧 {cut.frame} 超出总帧数 {self.frames}")
        if self.cuts and min(frames) != 1:
            raise ValueError("第一个切点必须在第 1 帧")
        for slot in self.reserved:
            if not 1 <= slot.start <= slot.end <= self.frames:
                raise ValueError(f"空段「{slot.label}」的起止帧无效")
        width, height = self.resolution
        if not (256 <= width <= 3840 and 256 <= height <= 3840):
            raise ValueError("分辨率须在 256–3840 之间")
        return self

    def segments(self) -> list[dict]:
        """按切点切出的镜头段：[{index, label, camera, start, end, seconds}]。"""
        cuts = sorted(self.cuts, key=lambda c: c.frame)
        out = []
        for index, cut in enumerate(cuts):
            end = cuts[index + 1].frame - 1 if index + 1 < len(cuts) else self.frames
            out.append({"index": index + 1, "label": cut.label, "camera": cut.camera, "start": cut.frame, "end": end,
                        "seconds": round((end - cut.frame + 1) / self.fps, 3)})
        return out
