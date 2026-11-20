"""Each video model takes its own number of references (Ark guide: Seedance 2.5 30/10/10, 2.5 flash 10/5/5, 2.0 9/3/3).

Before, every model was cut to Seedance 2.0's nine pictures: on 《钝刀》 ten of twelve clips sat at that cap.
"""

import base64
import io
import json
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from app.core import model_gateway, studio_canvas
from app.core.model_gateway import ModelGateway
from app.core.providers.capabilities import ProviderCapabilityRegistry
from app.core.reference_limits import ReferenceCaps, caps_of
from app.core.video_references import plan_video_references


def _pictures(count: int) -> list[str]:
    return [f"https://cdn.example/{index}.png" for index in range(count)]


def _inline_picture(side: int = 1600) -> str:
    noise = Image.effect_noise((side, side), 90).convert("RGB")
    buffer = io.BytesIO()
    noise.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class CapsTest(unittest.TestCase):
    def test_each_model_has_its_own_numbers(self):
        self.assertEqual(caps_of("seedance2.5"), ReferenceCaps(30, 10, 10))
        self.assertEqual(caps_of("doubao-seedance-2-5-260628"), ReferenceCaps(30, 10, 10))
        self.assertEqual(caps_of("doubao-seedance-2-5-flash-260815"), ReferenceCaps(10, 5, 5))
        self.assertEqual(caps_of("seedance2.0"), ReferenceCaps(9, 3, 3))
        self.assertEqual(caps_of("doubao-seedance-2-0-260128"), ReferenceCaps(9, 3, 3))
        self.assertEqual(caps_of("MiniMax-H3"), ReferenceCaps(9, 3, 3))
        self.assertEqual(caps_of(""), ReferenceCaps(9, 3, 3), "no model yet: the common cap")

    def test_the_registry_still_knows_every_seedance_name(self):
        seedance = ProviderCapabilityRegistry().get("seedance") if hasattr(ProviderCapabilityRegistry(), "get") else None
        registry = ProviderCapabilityRegistry()
        entry = seedance or registry._providers["seedance"]
        self.assertIn("seedance2.5", entry.aliases)
        self.assertIn("seedance2.0", entry.aliases)
        self.assertEqual((entry.limits["images"], entry.limits["videos"], entry.limits["audios"]), (30, 10, 10))


class PlanTest(unittest.TestCase):
    def test_a_25_shot_keeps_more_than_nine_pictures(self):
        plan = plan_video_references("multi_reference", first_frame=None, reference_images=_pictures(14), model="seedance2.5")
        self.assertEqual(len(plan.reference_images), 14)

    def test_it_keeps_to_the_model_that_really_renders(self):
        on_20 = plan_video_references("multi_reference", first_frame=None, reference_images=_pictures(14), model="seedance2.5", caps_model="seedance2.0")
        self.assertEqual(len(on_20.reference_images), 9)
        other_family = plan_video_references("multi_reference", first_frame=None, reference_images=_pictures(14), model="seedance2.5", caps_model="kling-o1")
        self.assertEqual(len(other_family.reference_images), 14, "another family's numbers do not apply to this plan")
        on_20_audio = plan_video_references(
            "multimodal", first_frame=None, reference_images=_pictures(2), reference_audios=_pictures(5), model="seedance2.5", caps_model="seedance2.0",
        )
        self.assertEqual(len(on_20_audio.reference_audios), 3)


class GatewayTest(unittest.TestCase):
    def _gateway(self) -> ModelGateway:
        gateway = ModelGateway.__new__(ModelGateway)
        gateway.seedance_model_name = "doubao-seedance-2-0-260128"
        gateway.tls_verify = True
        gateway._is_host_broken = lambda base: False
        gateway._proxies_for = lambda base: None
        return gateway

    def _sent(self, gateway: ModelGateway, **kwargs) -> dict:
        response = Mock(status_code=400, text="{}")
        response.json.return_value = {"error": {"code": "InvalidParameter", "message": "stop"}}
        with patch("requests.post", return_value=response) as post, self.assertLogs("app.core.model_gateway", level="WARNING"):
            gateway._ark_video("key", "https://ark.example/api/v3", "p", duration=5, **kwargs)
        return post.call_args.kwargs["json"]

    def test_the_request_carries_what_the_submitted_model_takes(self):
        gateway = self._gateway()
        on_25 = self._sent(gateway, ref_images=_pictures(14), ref_audios=_pictures(6), model_name="doubao-seedance-2-5-260628")
        roles = [item.get("role") for item in on_25["content"]]
        self.assertEqual((roles.count("reference_image"), roles.count("reference_audio")), (14, 6))
        on_20 = self._sent(gateway, ref_images=_pictures(14), ref_audios=_pictures(6))
        roles = [item.get("role") for item in on_20["content"]]
        self.assertEqual((roles.count("reference_image"), roles.count("reference_audio")), (9, 3), "no model named: the gateway's own 2.0")

    def test_without_a_centre_model_the_gateways_own_seedance_decides(self):
        gateway = self._gateway()
        with patch.object(model_gateway.runtime_model_registry, "resolve", return_value=None), \
                patch.object(ModelGateway, "effective_video_model", staticmethod(lambda model: model)):
            self.assertEqual(gateway.video_reference_model("seedance2.5"), "doubao-seedance-2-0-260128")
            self.assertEqual(gateway.video_reference_model("kling-o1"), "kling-o1")
            gateway.seedance_model_name = "doubao-seedream-4-5-251128"
            self.assertEqual(gateway.video_reference_model("seedance2.5"), "seedance2.5", "an image model there is not the renderer")

    def test_an_oversized_request_is_shrunk_then_cut_from_the_end(self):
        picture = _inline_picture()
        body = {"model": "m", "content": [{"type": "text", "text": "p"}, *[
            {"type": "image_url", "image_url": {"url": picture}, "role": "reference_image"} for _ in range(4)
        ]]}
        whole = len(json.dumps(body))
        with patch.object(model_gateway, "_table", side_effect=lambda key: {"ark_body_budget_bytes": whole * 10, "ark_shrink_side": 640, "ark_shrink_quality": 70}[key]):
            self.assertEqual(len(ModelGateway._fit_ark_body(json.loads(json.dumps(body)))["content"]), 5, "under budget: untouched")
        from app.core import reference_fit

        shrunk = reference_fit.compact_image_reference(picture, max_side=640, quality=70, force=True)
        bare = len(json.dumps({"model": "m", "content": [{"type": "text", "text": "p"}]}))
        item = len(json.dumps({"type": "image_url", "image_url": {"url": shrunk}, "role": "reference_image"})) + 2
        budget = bare + int(item * 2.5)
        with patch.object(model_gateway, "_table", side_effect=lambda key: {"ark_body_budget_bytes": budget, "ark_shrink_side": 640, "ark_shrink_quality": 70}[key]), \
                self.assertLogs("app.core.model_gateway", level="WARNING") as logs:
            fitted = ModelGateway._fit_ark_body(json.loads(json.dumps(body)))
        self.assertLessEqual(len(json.dumps(fitted, ensure_ascii=False)), budget)
        kept = [item for item in fitted["content"] if item.get("role") == "reference_image"]
        self.assertEqual(len(kept), 2, "shrunk first, then the last ones dropped")
        self.assertTrue(all(item["image_url"]["url"].startswith("data:image/jpeg") for item in kept))
        self.assertIn("丢掉了末尾", logs.output[0])


class CanvasTest(unittest.TestCase):
    def test_a_video_node_on_25_may_take_more_than_nine_pictures(self):
        too_many = [f"https://cdn.example/{index}.png" for index in range(12)]
        real = studio_canvas.Inputs

        def fresh():
            made = real()
            made.ref_images.extend(too_many)
            return made

        with patch.object(studio_canvas, "Inputs", side_effect=fresh):
            default = studio_canvas.resolve_inputs({"id": "v", "kind": "video_gen"}, {}, [], {}, lambda _id: [])
            on_25 = studio_canvas.resolve_inputs({"id": "v", "kind": "video_gen"}, {}, [], {}, lambda _id: [], caps=caps_of("seedance2.5"))
        self.assertTrue(any("12" in problem for problem in default.problems))
        self.assertFalse(any("12" in problem for problem in on_25.problems))


if __name__ == "__main__":
    unittest.main()
