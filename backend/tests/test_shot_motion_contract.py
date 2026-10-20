import unittest

from app.core.shot_motion_contract import (
    ShotMotionContract,
    assert_prompt_pair_consistent,
    compile_motion_prompt,
    compile_storyboard_image_prompt,
)
from tests.test_production_contracts import _panel


class ShotMotionContractTests(unittest.TestCase):
    def test_image_and_motion_prompts_share_one_fingerprint_and_all_assets(self):
        contract = ShotMotionContract.from_panel(_panel(1))
        image = compile_storyboard_image_prompt(contract)
        motion = compile_motion_prompt(contract)

        assert_prompt_pair_consistent(image, motion)
        self.assertEqual(image.contract_fingerprint, motion.contract_fingerprint)
        for prompt in (image.prompt, motion.prompt):
            for label in ("角色", "场景", "道具", "特效", "开始状态", "结束状态"):
                self.assertIn(label, prompt)

    def test_any_semantic_change_invalidates_existing_motion_plan(self):
        original = ShotMotionContract.from_panel(_panel(1))
        changed = original.model_copy(update={"camera_movement": "横向快速跟拍"})
        image = compile_storyboard_image_prompt(original)
        motion = compile_motion_prompt(changed)

        self.assertNotEqual(original.contract_fingerprint, changed.contract_fingerprint)
        with self.assertRaises(ValueError):
            assert_prompt_pair_consistent(image, motion)

    def test_provider_urls_do_not_change_the_semantic_contract(self):
        original = ShotMotionContract.from_panel(_panel(1))
        rebound = original.model_copy(update={
            "storyboard_image": "https://cdn.example/shot.png",
            "reference_images": ["https://cdn.example/character.png"],
        })
        self.assertEqual(original.contract_fingerprint, rebound.contract_fingerprint)
        self.assertNotEqual(original.artifact_fingerprint, rebound.artifact_fingerprint)


if __name__ == "__main__":
    unittest.main()
