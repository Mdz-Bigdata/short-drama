from __future__ import annotations

import json
import math
import struct
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from app.core import prompt_data


_WORDING_FILE = "uploads"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/uploads.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


MEBIBYTE = 1024 * 1024
# Largest single file accepted for an element image and for a GLB model. The
# request guard in request_limits.py allows these plus multipart overhead.
MAX_IMAGE_UPLOAD_BYTES = 10 * MEBIBYTE
MAX_MODEL_UPLOAD_BYTES = 25 * MEBIBYTE


class UploadValidationError(ValueError):
    pass


_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}

_GLB_MAGIC = b"glTF"
_GLB_JSON_CHUNK = 0x4E4F534A
_GLB_BIN_CHUNK = 0x004E4942
_GLB_ALLOWED_CONTENT_TYPES = {
    "application/octet-stream",
    "application/gltf-buffer",
    "model/gltf-binary",
}


def _document_array(document: dict, key: str) -> list:
    value = document.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise UploadValidationError(_text_of("_document_array.text").format(key))
    return value


def _ensure_json_depth(value: object, *, max_depth: int = 64) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            raise UploadValidationError(_text_of("_ensure_json_depth.text"))
        if isinstance(current, dict):
            stack.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, (int, float)) and not isinstance(current, bool):
            try:
                finite = math.isfinite(float(current))
            except (OverflowError, ValueError):
                finite = False
            if not finite:
                raise UploadValidationError(_text_of("_ensure_json_depth.text.2"))


def _used_extensions(value: object, names: set[str]) -> set[str]:
    stack = [value]
    found: set[str] = set()
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            extensions = current.get("extensions")
            if isinstance(extensions, dict):
                found.update(names.intersection(extensions))
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return found


def _all_extension_names(value: object) -> set[str]:
    stack = [value]
    found: set[str] = set()
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if "extensions" in current:
                extensions = current["extensions"]
                if not isinstance(extensions, dict):
                    raise UploadValidationError(_text_of("_all_extension_names.text"))
                found.update(str(name) for name in extensions)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return found


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _jpeg_dimensions(payload: bytes) -> tuple[int, int] | None:
    if not payload.startswith(b"\xff\xd8"):
        return None
    offset = 2
    start_of_frame = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while offset + 4 <= len(payload):
        if payload[offset] != 0xFF:
            return None
        while offset < len(payload) and payload[offset] == 0xFF:
            offset += 1
        if offset >= len(payload):
            return None
        marker = payload[offset]
        offset += 1
        if marker in {0x01, *range(0xD0, 0xD9)}:
            continue
        if offset + 2 > len(payload):
            return None
        segment_length = int.from_bytes(payload[offset:offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(payload):
            return None
        if marker in start_of_frame:
            if segment_length < 7:
                return None
            height = int.from_bytes(payload[offset + 3:offset + 5], "big")
            width = int.from_bytes(payload[offset + 5:offset + 7], "big")
            return width, height
        if marker == 0xDA:
            return None
        offset += segment_length
    return None


def _embedded_image_dimensions(payload: bytes, mime_type: str) -> tuple[int, int] | None:
    if mime_type == "image/png":
        if len(payload) < 24 or not payload.startswith(b"\x89PNG\r\n\x1a\n") or payload[12:16] != b"IHDR":
            return None
        return int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")
    if mime_type == "image/jpeg":
        return _jpeg_dimensions(payload)
    return None


def validate_image_upload(
    filename: str,
    content_type: str,
    content: bytes,
    *,
    max_bytes: int = MAX_IMAGE_UPLOAD_BYTES,
) -> str:
    if not content or len(content) > max_bytes:
        raise UploadValidationError(_text_of("validate_image_upload.text"))
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if declared not in _SIGNATURES:
        raise UploadValidationError(_text_of("validate_image_upload.text.2"))
    suffix = Path(filename or "").suffix.lower()
    allowed_suffixes = {
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/webp": {".webp"},
    }
    if suffix not in allowed_suffixes[declared]:
        raise UploadValidationError(_text_of("validate_image_upload.text.3"))
    if not any(content.startswith(prefix) for prefix in _SIGNATURES[declared]):
        raise UploadValidationError(_text_of("validate_image_upload.text.4"))
    if declared == "image/webp" and (len(content) < 12 or content[8:12] != b"WEBP"):
        raise UploadValidationError(_text_of("validate_image_upload.text.5"))
    return declared


def validate_glb_upload(
    filename: str,
    content_type: str,
    content: bytes,
    *,
    max_bytes: int = MAX_MODEL_UPLOAD_BYTES,
) -> str:
    inspect_glb_upload(filename, content_type, content, max_bytes=max_bytes)
    return "model/gltf-binary"


def inspect_glb_upload(
    filename: str,
    content_type: str,
    content: bytes,
    *,
    max_bytes: int = MAX_MODEL_UPLOAD_BYTES,
    max_triangles: int = 2_000_000,
    max_nodes: int = 5_000,
    max_materials: int = 256,
    max_textures: int = 128,
) -> dict:
    """Validate and return bounded, server-derived metadata for a glTF 2.0 binary."""
    if not content or len(content) > max_bytes:
        raise UploadValidationError(_text_of("inspect_glb_upload.text").format(MAX_MODEL_UPLOAD_BYTES // MEBIBYTE))
    if Path(filename or "").suffix.lower() != ".glb":
        raise UploadValidationError(_text_of("inspect_glb_upload.text.2"))
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if declared and declared not in _GLB_ALLOWED_CONTENT_TYPES:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.3"))
    if len(content) < 20 or content[:4] != _GLB_MAGIC:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.4"))

    version, declared_length = struct.unpack_from("<II", content, 4)
    if version != 2:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.5"))
    if declared_length != len(content):
        raise UploadValidationError(_text_of("inspect_glb_upload.text.6"))

    offset = 12
    json_document: dict | None = None
    chunk_index = 0
    bin_seen = False
    bin_chunk_length = 0
    bin_chunk_offset: int | None = None
    while offset < len(content):
        if offset + 8 > len(content):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.7"))
        chunk_length, chunk_type = struct.unpack_from("<II", content, offset)
        offset += 8
        chunk_end = offset + chunk_length
        if chunk_length % 4 or chunk_end > len(content):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.8"))
        if chunk_type == _GLB_JSON_CHUNK:
            if chunk_index != 0 or json_document is not None:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.9"))
            if chunk_length > 2 * 1024 * 1024:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.10"))
            try:
                decoded = content[offset:chunk_end].rstrip(b" ").decode("utf-8")
                candidate = json.loads(decoded, parse_constant=_reject_json_constant)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.11")) from exc
            if not isinstance(candidate, dict):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.12"))
            _ensure_json_depth(candidate)
            json_document = candidate
        elif chunk_type == _GLB_BIN_CHUNK:
            if bin_seen:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.13"))
            bin_seen = True
            bin_chunk_length = chunk_length
            bin_chunk_offset = offset
        else:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.14"))
        offset = chunk_end
        chunk_index += 1

    if offset != len(content) or json_document is None:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.15"))
    asset = json_document.get("asset")
    if not isinstance(asset, dict) or asset.get("version") != "2.0":
        raise UploadValidationError(_text_of("inspect_glb_upload.text.16"))

    unsupported_compression = {
        "EXT_meshopt_compression",
        "KHR_draco_mesh_compression",
        "KHR_texture_basisu",
    }
    required_extensions = _document_array(json_document, "extensionsRequired")
    declared_extensions = _document_array(json_document, "extensionsUsed")
    if any(not isinstance(name, str) for name in required_extensions):
        raise UploadValidationError(_text_of("inspect_glb_upload.text.17"))
    if any(not isinstance(name, str) for name in declared_extensions):
        raise UploadValidationError(_text_of("inspect_glb_upload.text.18"))
    extension_names = set(required_extensions) | set(declared_extensions) | _all_extension_names(json_document)
    used_unsupported = unsupported_compression.intersection(extension_names)
    used_unsupported.update(_used_extensions(json_document, unsupported_compression))
    if used_unsupported:
        names = "、".join(sorted(used_unsupported))
        raise UploadValidationError(_text_of("inspect_glb_upload.text.19").format(names))
    if not set(required_extensions).issubset(declared_extensions):
        raise UploadValidationError(_text_of("inspect_glb_upload.text.20"))
    if extension_names:
        names = "、".join(sorted(extension_names))
        raise UploadValidationError(_text_of("inspect_glb_upload.text.21").format(names))

    def bounded_int(value: object, label: str, *, minimum: int = 0, maximum: int | None = None) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise UploadValidationError(_text_of("bounded_int.text").format(label))
        if maximum is not None and value > maximum:
            raise UploadValidationError(_text_of("bounded_int.text.2").format(label, maximum))
        return value

    def finite_vector(value: object, label: str, length: int) -> None:
        if not isinstance(value, list) or len(value) != length:
            raise UploadValidationError(_text_of("finite_vector.text").format(label))
        for number in value:
            finite_number(number, label)

    def finite_number(
        value: object,
        label: str,
        *,
        minimum: float | None = None,
        strictly_positive: bool = False,
    ) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UploadValidationError(_text_of("finite_number.text").format(label))
        try:
            resolved = float(value)
        except (OverflowError, ValueError) as exc:
            raise UploadValidationError(_text_of("finite_number.text.2").format(label)) from exc
        if not math.isfinite(resolved):
            raise UploadValidationError(_text_of("finite_number.text.3").format(label))
        if strictly_positive and resolved <= 0:
            raise UploadValidationError(_text_of("finite_number.text.4").format(label))
        if minimum is not None and resolved < minimum:
            raise UploadValidationError(_text_of("finite_number.text.5").format(label, minimum))
        return resolved

    # GLB uploads are intentionally self-contained. Even an empty URI key is
    # rejected so the browser loader can never resolve a resource externally.
    buffers = _document_array(json_document, "buffers")
    images = _document_array(json_document, "images")
    resources = [*buffers, *images]
    if any(not isinstance(resource, dict) for resource in resources):
        raise UploadValidationError(_text_of("inspect_glb_upload.text.22"))
    if any("uri" in resource for resource in resources):
        raise UploadValidationError(_text_of("inspect_glb_upload.text.23"))
    if len(buffers) > 1:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.24"))

    buffer_byte_length = 0
    if buffers:
        buffer_byte_length = bounded_int(buffers[0].get("byteLength"), "buffer.byteLength")
        if not bin_seen and buffer_byte_length:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.25"))
        if bin_seen and not (buffer_byte_length <= bin_chunk_length <= buffer_byte_length + 3):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.26"))
    elif bin_seen and bin_chunk_length:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.27"))

    buffer_views = _document_array(json_document, "bufferViews")
    if len(buffer_views) > 4_096:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.28"))
    view_infos: list[dict] = []
    for view in buffer_views:
        if not isinstance(view, dict):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.29"))
        buffer_index = bounded_int(view.get("buffer"), "bufferView.buffer")
        if buffer_index != 0 or not buffers:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.30"))
        byte_offset = bounded_int(view.get("byteOffset", 0), "bufferView.byteOffset")
        byte_length = bounded_int(view.get("byteLength"), "bufferView.byteLength", minimum=1)
        if byte_offset + byte_length > buffer_byte_length:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.31"))
        byte_stride = view.get("byteStride")
        if byte_stride is not None:
            byte_stride = bounded_int(byte_stride, "bufferView.byteStride", minimum=4, maximum=252)
            if byte_stride % 4:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.32"))
        view_infos.append({"offset": byte_offset, "length": byte_length, "stride": byte_stride})

    accessors = _document_array(json_document, "accessors")
    if len(accessors) > 8_192:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.33"))
    component_sizes = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
    type_shapes = {
        "SCALAR": (1, 1, 1), "VEC2": (2, 1, 2), "VEC3": (3, 1, 3), "VEC4": (4, 1, 4),
        "MAT2": (4, 2, 2), "MAT3": (9, 3, 3), "MAT4": (16, 4, 4),
    }
    accessor_infos: list[dict] = []
    total_accessor_elements = 0
    total_accessor_components = 0
    for accessor in accessors:
        if not isinstance(accessor, dict):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.34"))
        if "sparse" in accessor:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.35"))
        view_index = bounded_int(accessor.get("bufferView"), "accessor.bufferView")
        if view_index >= len(view_infos):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.36"))
        component_type = bounded_int(accessor.get("componentType"), "accessor.componentType")
        if component_type not in component_sizes:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.37"))
        accessor_type = accessor.get("type")
        if accessor_type not in type_shapes:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.38"))
        count = bounded_int(accessor.get("count"), "accessor.count", minimum=1, maximum=5_000_000)
        total_accessor_elements += count
        if total_accessor_elements > 10_000_000:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.39"))
        component_count, columns, rows = type_shapes[accessor_type]
        total_accessor_components += count * component_count
        if total_accessor_components > 25_000_000:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.40"))
        component_size = component_sizes[component_type]
        column_size = rows * component_size
        element_size = columns * ((column_size + 3) // 4 * 4) if columns > 1 and component_size < 4 else component_count * component_size
        accessor_offset = bounded_int(accessor.get("byteOffset", 0), "accessor.byteOffset")
        view = view_infos[view_index]
        if (view["offset"] + accessor_offset) % component_size:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.41"))
        stride = view["stride"] or element_size
        if stride < element_size or stride % component_size:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.42"))
        accessor_end = accessor_offset + (count - 1) * stride + element_size
        if accessor_end > view["length"]:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.43"))
        normalized = accessor.get("normalized", False)
        if not isinstance(normalized, bool) or (normalized and component_type == 5126):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.44"))
        for boundary in ("min", "max"):
            if boundary in accessor:
                finite_vector(accessor[boundary], f"accessor.{boundary}", component_count)
        if "min" in accessor and "max" in accessor:
            if any(minimum > maximum for minimum, maximum in zip(accessor["min"], accessor["max"])):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.45"))
        if component_type == 5126:
            if bin_chunk_offset is None:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.46"))
            unpack_float_values = struct.Struct(f"<{component_count}f")
            first_value_offset = bin_chunk_offset + view["offset"] + accessor_offset
            for element_index in range(count):
                values = unpack_float_values.unpack_from(
                    content,
                    first_value_offset + element_index * stride,
                )
                if any(not math.isfinite(value) for value in values):
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.47"))
        accessor_infos.append({
            "count": count,
            "componentType": component_type,
            "type": accessor_type,
        })

    def accessor_info(index: object, label: str) -> dict:
        resolved = bounded_int(index, label)
        if resolved >= len(accessor_infos):
            raise UploadValidationError(_text_of("accessor_info.text").format(label))
        return accessor_infos[resolved]

    nodes = _document_array(json_document, "nodes")
    meshes = _document_array(json_document, "meshes")
    materials = _document_array(json_document, "materials")
    samplers = _document_array(json_document, "samplers")
    textures = _document_array(json_document, "textures")
    animations = _document_array(json_document, "animations")
    cameras = _document_array(json_document, "cameras")
    if len(nodes) > max_nodes:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.48").format(max_nodes))
    if len(meshes) > 1_024:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.49"))
    if len(materials) > max_materials or any(not isinstance(material, dict) for material in materials):
        raise UploadValidationError(_text_of("inspect_glb_upload.text.50").format(max_materials))
    if len(textures) > max_textures or len(images) > max_textures:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.51").format(max_textures))
    if len(samplers) > max_textures:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.52").format(max_textures))
    if len(cameras) > 256:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.53"))

    total_texture_pixels = 0
    for image in images:
        view_index = bounded_int(image.get("bufferView"), "image.bufferView")
        if view_index >= len(view_infos):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.54"))
        mime_type = image.get("mimeType")
        if mime_type not in {"image/png", "image/jpeg"}:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.55"))
        if bin_chunk_offset is None:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.56"))
        view = view_infos[view_index]
        if view["stride"] is not None:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.57"))
        image_start = bin_chunk_offset + view["offset"]
        image_payload = content[image_start:image_start + view["length"]]
        dimensions = _embedded_image_dimensions(image_payload, mime_type)
        if not dimensions:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.58"))
        width, height = dimensions
        pixels = width * height
        if width <= 0 or height <= 0 or width > 8_192 or height > 8_192 or pixels > 33_554_432:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.59"))
        try:
            with Image.open(BytesIO(image_payload)) as decoded_image:
                expected_format = "PNG" if mime_type == "image/png" else "JPEG"
                if decoded_image.format != expected_format or decoded_image.size != dimensions:
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.60"))
                decoded_image.verify()
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.61")) from exc
        total_texture_pixels += pixels
        if total_texture_pixels > 67_108_864:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.62"))
    for texture in textures:
        if not isinstance(texture, dict):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.63"))
        source = bounded_int(texture.get("source"), "texture.source")
        if source >= len(images):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.64"))
        if "sampler" in texture:
            sampler_index = bounded_int(texture["sampler"], "texture.sampler")
            if sampler_index >= len(samplers):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.65"))

    for sampler in samplers:
        if not isinstance(sampler, dict):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.66"))
        if "magFilter" in sampler and sampler["magFilter"] not in {9728, 9729}:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.67"))
        if "minFilter" in sampler and sampler["minFilter"] not in {9728, 9729, 9984, 9985, 9986, 9987}:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.68"))
        for wrap_key in ("wrapS", "wrapT"):
            if wrap_key in sampler and sampler[wrap_key] not in {33071, 33648, 10497}:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.69").format(wrap_key))

    def texture_info(value: object, label: str) -> dict:
        if not isinstance(value, dict):
            raise UploadValidationError(_text_of("texture_info.text").format(label))
        texture_index = bounded_int(value.get("index"), f"{label}.index")
        if texture_index >= len(textures):
            raise UploadValidationError(_text_of("texture_info.text.2").format(label))
        if "texCoord" in value:
            bounded_int(value["texCoord"], f"{label}.texCoord", maximum=31)
        return value

    for material_index, material in enumerate(materials):
        prefix = f"material[{material_index}]"
        pbr = material.get("pbrMetallicRoughness", {})
        if not isinstance(pbr, dict):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.70").format(prefix))
        if "baseColorFactor" in pbr:
            finite_vector(pbr["baseColorFactor"], f"{prefix}.baseColorFactor", 4)
        if "metallicFactor" in pbr:
            metallic = finite_number(pbr["metallicFactor"], f"{prefix}.metallicFactor", minimum=0)
            if metallic > 1:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.71").format(prefix))
        if "roughnessFactor" in pbr:
            roughness = finite_number(pbr["roughnessFactor"], f"{prefix}.roughnessFactor", minimum=0)
            if roughness > 1:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.72").format(prefix))
        for key in ("baseColorTexture", "metallicRoughnessTexture"):
            if key in pbr:
                texture_info(pbr[key], f"{prefix}.{key}")
        if "normalTexture" in material:
            info = texture_info(material["normalTexture"], f"{prefix}.normalTexture")
            if "scale" in info:
                finite_number(info["scale"], f"{prefix}.normalTexture.scale")
        if "occlusionTexture" in material:
            info = texture_info(material["occlusionTexture"], f"{prefix}.occlusionTexture")
            if "strength" in info:
                strength = finite_number(info["strength"], f"{prefix}.occlusionTexture.strength", minimum=0)
                if strength > 1:
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.73").format(prefix))
        if "emissiveTexture" in material:
            texture_info(material["emissiveTexture"], f"{prefix}.emissiveTexture")
        if "emissiveFactor" in material:
            finite_vector(material["emissiveFactor"], f"{prefix}.emissiveFactor", 3)
        if material.get("alphaMode", "OPAQUE") not in {"OPAQUE", "MASK", "BLEND"}:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.74").format(prefix))
        if "alphaCutoff" in material:
            finite_number(material["alphaCutoff"], f"{prefix}.alphaCutoff", minimum=0)
        if "doubleSided" in material and not isinstance(material["doubleSided"], bool):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.75").format(prefix))

    for camera_index, camera in enumerate(cameras):
        prefix = f"camera[{camera_index}]"
        if not isinstance(camera, dict) or camera.get("type") not in {"perspective", "orthographic"}:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.76").format(prefix))
        settings = camera.get(camera["type"])
        if not isinstance(settings, dict):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.77").format(prefix, camera['type']))
        if camera["type"] == "perspective":
            finite_number(settings.get("yfov"), f"{prefix}.perspective.yfov", strictly_positive=True)
            near = finite_number(settings.get("znear"), f"{prefix}.perspective.znear", strictly_positive=True)
            if "aspectRatio" in settings:
                finite_number(settings["aspectRatio"], f"{prefix}.perspective.aspectRatio", strictly_positive=True)
            if "zfar" in settings:
                far = finite_number(settings["zfar"], f"{prefix}.perspective.zfar", strictly_positive=True)
                if far <= near:
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.78").format(prefix))
        else:
            finite_number(settings.get("xmag"), f"{prefix}.orthographic.xmag", strictly_positive=True)
            finite_number(settings.get("ymag"), f"{prefix}.orthographic.ymag", strictly_positive=True)
            near = finite_number(settings.get("znear"), f"{prefix}.orthographic.znear", minimum=0)
            far = finite_number(settings.get("zfar"), f"{prefix}.orthographic.zfar", strictly_positive=True)
            if far <= near:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.79").format(prefix))

    vertices = 0
    triangles = 0
    primitive_count = 0
    mesh_triangles: list[int] = []
    mesh_primitives: list[int] = []
    mesh_morph_targets: list[int] = []
    for mesh in meshes:
        if not isinstance(mesh, dict):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.80"))
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list) or not primitives:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.81"))
        if "weights" in mesh:
            weights = mesh["weights"]
            if not isinstance(weights, list) or len(weights) > 16:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.82"))
            for weight in weights:
                finite_number(weight, "mesh.weights")
        current_mesh_triangles = 0
        morph_target_count: int | None = None
        for primitive in primitives:
            primitive_count += 1
            if primitive_count > 4_096:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.83"))
            if not isinstance(primitive, dict):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.84"))
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.85"))
            for semantic, accessor_index in attributes.items():
                if not isinstance(semantic, str):
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.86"))
                accessor_info(accessor_index, f"attribute.{semantic}")
            position = accessor_info(attributes["POSITION"], "attribute.POSITION")
            if position["type"] != "VEC3":
                raise UploadValidationError(_text_of("inspect_glb_upload.text.87"))
            vertex_count = position["count"]
            vertices += vertex_count
            if "indices" in primitive:
                indices = accessor_info(primitive["indices"], "primitive.indices")
                if indices["type"] != "SCALAR" or indices["componentType"] not in {5121, 5123, 5125}:
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.88"))
                draw_count = indices["count"]
            else:
                draw_count = vertex_count
            mode = bounded_int(primitive.get("mode", 4), "primitive.mode", maximum=6)
            primitive_triangles = 0
            if mode == 4:
                primitive_triangles = draw_count // 3
            elif mode in {5, 6}:
                primitive_triangles = max(draw_count - 2, 0)
            current_mesh_triangles += primitive_triangles
            triangles += primitive_triangles
            if "material" in primitive:
                material_index = bounded_int(primitive["material"], "primitive.material")
                if material_index >= len(materials):
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.89"))
            targets = primitive.get("targets", [])
            if not isinstance(targets, list):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.90"))
            if len(targets) > 16:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.91"))
            if morph_target_count is None:
                morph_target_count = len(targets)
            elif len(targets) != morph_target_count:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.92"))
            for target in targets:
                if not isinstance(target, dict):
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.93"))
                for semantic, accessor_index in target.items():
                    accessor_info(accessor_index, f"morphTarget.{semantic}")
        if "weights" in mesh and len(mesh["weights"]) != (morph_target_count or 0):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.94"))
        mesh_triangles.append(current_mesh_triangles)
        mesh_primitives.append(len(primitives))
        mesh_morph_targets.append(morph_target_count or 0)
    if triangles > max_triangles:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.95").format(max_triangles))

    node_children: list[list[int]] = []
    node_meshes: list[int | None] = []
    parent_counts = [0] * len(nodes)
    effective_triangles = 0
    draw_calls = 0
    for node in nodes:
        if not isinstance(node, dict):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.96"))
        children = node.get("children", [])
        if not isinstance(children, list) or len(children) > max_nodes:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.97").format(max_nodes))
        resolved_children = []
        seen_children: set[int] = set()
        for child in children:
            child_index = bounded_int(child, "node.children")
            if child_index >= len(nodes):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.98"))
            if child_index in seen_children:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.99"))
            seen_children.add(child_index)
            parent_counts[child_index] += 1
            if parent_counts[child_index] > 1:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.100"))
            resolved_children.append(child_index)
        node_children.append(resolved_children)
        mesh_index: int | None = None
        if "mesh" in node:
            mesh_index = bounded_int(node["mesh"], "node.mesh")
            if mesh_index >= len(meshes):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.101"))
            effective_triangles += mesh_triangles[mesh_index]
            draw_calls += mesh_primitives[mesh_index]
        node_meshes.append(mesh_index)
        if "camera" in node:
            camera_index = bounded_int(node["camera"], "node.camera")
            if camera_index >= len(cameras):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.102"))
        if "skin" in node:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.103"))
        if "weights" in node:
            weights = node["weights"]
            if not isinstance(weights, list) or len(weights) > 16:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.104"))
            if mesh_index is None or len(weights) != mesh_morph_targets[mesh_index]:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.105"))
            for weight in weights:
                finite_number(weight, "node.weights")
        has_matrix = "matrix" in node
        if has_matrix:
            finite_vector(node["matrix"], "node.matrix", 16)
            if any(key in node for key in ("translation", "rotation", "scale")):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.106"))
        if "translation" in node:
            finite_vector(node["translation"], "node.translation", 3)
        if "rotation" in node:
            finite_vector(node["rotation"], "node.rotation", 4)
        if "scale" in node:
            finite_vector(node["scale"], "node.scale", 3)
    if effective_triangles > max_triangles:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.107").format(max_triangles))
    if draw_calls > 8_192:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.108"))

    colors = [0] * len(nodes)
    for root_index in range(len(nodes)):
        if colors[root_index]:
            continue
        stack: list[tuple[int, bool]] = [(root_index, False)]
        while stack:
            node_index, exiting = stack.pop()
            if exiting:
                colors[node_index] = 2
                continue
            if colors[node_index] == 1:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.109"))
            if colors[node_index] == 2:
                continue
            colors[node_index] = 1
            stack.append((node_index, True))
            for child_index in reversed(node_children[node_index]):
                if colors[child_index] == 1:
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.110"))
                if colors[child_index] == 0:
                    stack.append((child_index, False))

    scenes = _document_array(json_document, "scenes")
    if len(scenes) > 16:
        raise UploadValidationError(_text_of("inspect_glb_upload.text.111"))
    scene_triangles: list[int] = []
    scene_draw_calls: list[int] = []
    total_scene_nodes = 0
    total_scene_triangles = 0
    total_scene_draw_calls = 0
    for scene in scenes:
        if not isinstance(scene, dict) or not isinstance(scene.get("nodes", []), list):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.112"))
        roots = scene.get("nodes", [])
        if len(roots) > max_nodes:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.113").format(max_nodes))
        resolved_roots: list[int] = []
        seen_roots: set[int] = set()
        for node_index in roots:
            resolved = bounded_int(node_index, "scene.nodes")
            if resolved >= len(nodes):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.114"))
            if resolved in seen_roots:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.115"))
            if parent_counts[resolved]:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.116"))
            seen_roots.add(resolved)
            resolved_roots.append(resolved)

        visited: set[int] = set()
        current_triangles = 0
        current_draw_calls = 0
        stack = list(reversed(resolved_roots))
        while stack:
            node_index = stack.pop()
            if node_index in visited:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.117"))
            visited.add(node_index)
            if len(visited) > max_nodes:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.118").format(max_nodes))
            mesh_index = node_meshes[node_index]
            if mesh_index is not None:
                current_triangles += mesh_triangles[mesh_index]
                current_draw_calls += mesh_primitives[mesh_index]
                if current_triangles > max_triangles:
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.119").format(max_triangles))
                if current_draw_calls > 8_192:
                    raise UploadValidationError(_text_of("inspect_glb_upload.text.120"))
            stack.extend(reversed(node_children[node_index]))

        scene_triangles.append(current_triangles)
        scene_draw_calls.append(current_draw_calls)
        total_scene_nodes += len(visited)
        total_scene_triangles += current_triangles
        total_scene_draw_calls += current_draw_calls
        if total_scene_nodes > max_nodes * 2:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.121").format(max_nodes * 2))
        if total_scene_triangles > max_triangles * 2:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.122").format(max_triangles * 2))
        if total_scene_draw_calls > 16_384:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.123"))

    default_scene_index = 0
    if "scene" in json_document:
        default_scene_index = bounded_int(json_document["scene"], "scene")
        if default_scene_index >= len(scenes):
            raise UploadValidationError(_text_of("inspect_glb_upload.text.124"))
    if _document_array(json_document, "skins"):
        raise UploadValidationError(_text_of("inspect_glb_upload.text.125"))
    if len(animations) > 128 or any(not isinstance(animation, dict) for animation in animations):
        raise UploadValidationError(_text_of("inspect_glb_upload.text.126"))
    for animation_index, animation in enumerate(animations):
        prefix = f"animation[{animation_index}]"
        animation_samplers = animation.get("samplers")
        channels = animation.get("channels")
        if not isinstance(animation_samplers, list) or not animation_samplers:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.127").format(prefix))
        if not isinstance(channels, list) or not channels:
            raise UploadValidationError(_text_of("inspect_glb_upload.text.128").format(prefix))
        resolved_samplers: list[tuple[dict, dict, str]] = []
        for sampler_index, sampler in enumerate(animation_samplers):
            if not isinstance(sampler, dict):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.129").format(prefix, sampler_index))
            input_accessor = accessor_info(sampler.get("input"), f"{prefix}.sampler.input")
            output_accessor = accessor_info(sampler.get("output"), f"{prefix}.sampler.output")
            interpolation = sampler.get("interpolation", "LINEAR")
            if interpolation not in {"LINEAR", "STEP", "CUBICSPLINE"}:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.130").format(prefix))
            if input_accessor["type"] != "SCALAR" or input_accessor["componentType"] != 5126:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.131").format(prefix))
            resolved_samplers.append((input_accessor, output_accessor, interpolation))
        for channel_index, channel in enumerate(channels):
            if not isinstance(channel, dict) or not isinstance(channel.get("target"), dict):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.132").format(prefix, channel_index))
            sampler_index = bounded_int(channel.get("sampler"), f"{prefix}.channel.sampler")
            if sampler_index >= len(resolved_samplers):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.133").format(prefix))
            target = channel["target"]
            node_index = bounded_int(target.get("node"), f"{prefix}.channel.target.node")
            if node_index >= len(nodes):
                raise UploadValidationError(_text_of("inspect_glb_upload.text.134").format(prefix))
            path = target.get("path")
            expected_type = {"translation": "VEC3", "rotation": "VEC4", "scale": "VEC3", "weights": "SCALAR"}.get(path)
            if expected_type is None:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.135").format(prefix))
            input_accessor, output_accessor, interpolation = resolved_samplers[sampler_index]
            if output_accessor["type"] != expected_type:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.136").format(prefix))
            expected_multiplier = 3 if interpolation == "CUBICSPLINE" else 1
            if output_accessor["count"] < input_accessor["count"] * expected_multiplier:
                raise UploadValidationError(_text_of("inspect_glb_upload.text.137").format(prefix))

    displayed_triangles = scene_triangles[default_scene_index] if scenes else effective_triangles
    displayed_draw_calls = scene_draw_calls[default_scene_index] if scenes else draw_calls
    return {
        "nodes": len(nodes),
        "meshes": len(meshes),
        "vertices": vertices,
        "triangles": displayed_triangles,
        "materials": len(materials),
        "textures": len(textures),
        "animations": len(animations),
        "drawCalls": displayed_draw_calls,
    }
