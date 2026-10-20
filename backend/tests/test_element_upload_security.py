import json
import struct
import unittest

from app.platform.uploads import UploadValidationError, validate_glb_upload, validate_image_upload


def _glb(document: dict, binary: bytes = b"", *, padding: bytes = b" ") -> bytes:
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += padding * (-len(payload) % 4)
    chunks = struct.pack("<II", len(payload), 0x4E4F534A) + payload
    if binary:
        padded_binary = binary + b"\x00" * (-len(binary) % 4)
        chunks += struct.pack("<II", len(padded_binary), 0x004E4942) + padded_binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def _glb_documents(*documents: dict) -> bytes:
    chunks = b""
    for document in documents:
        payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
        payload += b" " * (-len(payload) % 4)
        chunks += struct.pack("<II", len(payload), 0x4E4F534A) + payload
    length = 12 + len(chunks)
    return b"glTF" + struct.pack("<II", 2, length) + chunks


class ElementUploadSecurityTests(unittest.TestCase):
    def test_only_real_bounded_raster_images_are_accepted(self):
        png = b"\x89PNG\r\n\x1a\n" + b"safe-image-bytes"
        self.assertEqual(validate_image_upload("portrait.png", "image/png", png), "image/png")

        with self.assertRaises(UploadValidationError):
            validate_image_upload("payload.png", "image/png", b"<script>alert(1)</script>")
        with self.assertRaises(UploadValidationError):
            validate_image_upload("vector.svg", "image/svg+xml", b"<svg></svg>")
        with self.assertRaises(UploadValidationError):
            validate_image_upload("huge.png", "image/png", png * 1_000_000, max_bytes=1024)

    def test_only_self_contained_gltf_2_glb_models_are_accepted(self):
        model = _glb({"asset": {"version": "2.0"}, "scenes": [{}], "scene": 0})
        self.assertEqual(
            validate_glb_upload("set.glb", "application/octet-stream", model),
            "model/gltf-binary",
        )

        with self.assertRaisesRegex(UploadValidationError, "GLB 文件头"):
            validate_glb_upload("fake.glb", "model/gltf-binary", b"<script>alert(1)</script>")
        with self.assertRaisesRegex(UploadValidationError, "自包含"):
            validate_glb_upload("set.gltf", "model/gltf-binary", model)
        with self.assertRaisesRegex(UploadValidationError, "不能包含外部资源"):
            validate_glb_upload(
                "remote.glb",
                "model/gltf-binary",
                _glb({"asset": {"version": "2.0"}, "buffers": [{"uri": "https://example.test/a.bin"}]}),
            )
        with self.assertRaisesRegex(UploadValidationError, "不能包含外部资源"):
            validate_glb_upload(
                "empty-uri.glb",
                "model/gltf-binary",
                _glb({"asset": {"version": "2.0"}, "images": [{"uri": ""}]}),
            )
        with self.assertRaisesRegex(UploadValidationError, "未启用的压缩扩展"):
            validate_glb_upload(
                "compressed.glb",
                "model/gltf-binary",
                _glb({
                    "asset": {"version": "2.0"},
                    "extensionsRequired": ["KHR_draco_mesh_compression"],
                }),
            )
        with self.assertRaisesRegex(UploadValidationError, "只能包含一个"):
            validate_glb_upload(
                "dual-json.glb",
                "model/gltf-binary",
                _glb_documents(
                    {"asset": {"version": "2.0"}},
                    {"asset": {"version": "2.0"}, "images": [{"uri": "https://evil.test/track.png"}]},
                ),
            )
        with self.assertRaisesRegex(UploadValidationError, "accessor.bufferView"):
            validate_glb_upload(
                "invalid-accessor.glb",
                "model/gltf-binary",
                _glb({
                    "asset": {"version": "2.0"},
                    "accessors": [{"count": 3}],
                    "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
                }),
            )
        with self.assertRaisesRegex(UploadValidationError, "无效 texture"):
            validate_glb_upload(
                "broken-material.glb",
                "model/gltf-binary",
                _glb({
                    "asset": {"version": "2.0"},
                    "materials": [{
                        "pbrMetallicRoughness": {"baseColorTexture": {"index": 99}},
                    }],
                }),
            )
        with self.assertRaisesRegex(UploadValidationError, "场景描述无效"):
            validate_glb_upload(
                "non-finite.glb",
                "model/gltf-binary",
                _glb({"asset": {"version": "2.0"}, "extras": {"unsafe": float("nan")}}),
            )
        nul_padded_document = {"asset": {"version": "2.0"}, "extras": {"pad": "xx"}}
        while len(json.dumps(nul_padded_document, separators=(",", ":")).encode("utf-8")) % 4 == 0:
            nul_padded_document["extras"]["pad"] += "x"
        with self.assertRaisesRegex(UploadValidationError, "场景描述无效"):
            validate_glb_upload(
                "nul-padding.glb",
                "model/gltf-binary",
                _glb(nul_padded_document, padding=b"\x00"),
            )
        non_finite_positions = struct.pack("<9f", float("nan"), 0, 0, 1, 0, 0, 0, 1, 0)
        with self.assertRaisesRegex(UploadValidationError, "NaN 或 Infinity"):
            validate_glb_upload(
                "nan-position.glb",
                "model/gltf-binary",
                _glb({
                    "asset": {"version": "2.0"},
                    "buffers": [{"byteLength": len(non_finite_positions)}],
                    "bufferViews": [{"buffer": 0, "byteLength": len(non_finite_positions)}],
                    "accessors": [{
                        "bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
                    }],
                    "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
                }, non_finite_positions),
            )
        malformed_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", 1, 1)
        with self.assertRaisesRegex(UploadValidationError, "无法安全解码"):
            validate_glb_upload(
                "broken-texture.glb",
                "model/gltf-binary",
                _glb({
                    "asset": {"version": "2.0"},
                    "buffers": [{"byteLength": len(malformed_png)}],
                    "bufferViews": [{"buffer": 0, "byteLength": len(malformed_png)}],
                    "images": [{"bufferView": 0, "mimeType": "image/png"}],
                }, malformed_png),
            )
        with self.assertRaisesRegex(UploadValidationError, "25 MB"):
            validate_glb_upload("huge.glb", "model/gltf-binary", model * 2, max_bytes=len(model))

    def test_scene_graph_rejects_duplicate_instances_before_browser_loading(self):
        with self.assertRaisesRegex(UploadValidationError, "重复引用同一根节点"):
            validate_glb_upload(
                "duplicate-roots.glb",
                "model/gltf-binary",
                _glb({
                    "asset": {"version": "2.0"},
                    "nodes": [{"name": "single-node"}],
                    "scenes": [{"nodes": [0, 0]}],
                    "scene": 0,
                }),
            )

        with self.assertRaisesRegex(UploadValidationError, "多个父节点"):
            validate_glb_upload(
                "shared-child.glb",
                "model/gltf-binary",
                _glb({
                    "asset": {"version": "2.0"},
                    "nodes": [{"children": [2]}, {"children": [2]}, {}],
                    "scenes": [{"nodes": [0, 1]}],
                    "scene": 0,
                }),
            )


if __name__ == "__main__":
    unittest.main()
