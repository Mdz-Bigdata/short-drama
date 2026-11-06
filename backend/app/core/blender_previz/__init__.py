"""Blender 3D 预演台：把空间方案搭成白模、渲染成运动参考，并与打开的 Blender 实时同步。"""

from .from_plan import build_spec, operations_from_snapshot
from .spec import BlockingSpec

__all__ = ["BlockingSpec", "build_spec", "operations_from_snapshot"]
