# -*- coding: utf-8 -*-
import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.auth_api import auth_service
from app.platform.dependencies import get_platform_store
from app.platform.store import MAX_DESK_POSES_PER_OWNER, PlatformStore
from main import app

POSE = {"preset": "kneel-one", "joints": {"leftKnee.bend": 86, "rightHand.index.curl": 70}}


class UserPoseLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'poses.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            self.user, _ = await self.store.create_user(email="poser@example.com", phone=None, password="user-password-strong")
            self.other, _ = await self.store.create_user(email="other@example.com", phone=None, password="user-password-strong")

        asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        asyncio.run(self.store.close())
        self.temp.cleanup()

    def _as(self, user) -> dict:
        return {"auth_token": auth_service.generate_token(user.id)}

    def _save(self, user, name, pose=POSE):
        return self.client.post("/api/director-desk/poses", json={"name": name, "pose": pose}, cookies=self._as(user))

    def test_the_library_needs_a_signed_in_person(self):
        self.assertEqual(self.client.get("/api/director-desk/poses").status_code, 401)

    def test_poses_belong_to_the_person_not_to_a_project(self):
        saved = self._save(self.user, " 单膝持剑 ")
        self.assertEqual(saved.status_code, 200, saved.text)
        [pose] = saved.json()["poses"]
        self.assertEqual((pose["name"], pose["pose"]["preset"]), ("单膝持剑", "kneel-one"))
        self.assertEqual(pose["pose"]["joints"], {"leftKnee.bend": 86.0, "rightHand.index.curl": 70.0})
        self.assertEqual(pose["pose"]["clip_phase"], 0.0)

        # No task id anywhere in the route: whichever project is open, this is what comes back.
        listed = self.client.get("/api/director-desk/poses", cookies=self._as(self.user)).json()
        self.assertEqual([item["id"] for item in listed["poses"]], [pose["id"]])
        self.assertEqual(self.client.get("/api/director-desk/poses", cookies=self._as(self.other)).json()["poses"], [])

        # The same name is free for somebody else, and replaces in place for its owner.
        self.assertEqual(self._save(self.other, "单膝持剑").status_code, 200)
        replaced = self._save(self.user, "单膝持剑", {"preset": "sit"}).json()["poses"]
        self.assertEqual([(item["id"], item["pose"]["preset"]) for item in replaced], [(pose["id"], "sit")])

    def test_bad_names_and_poses_are_refused(self):
        self.assertEqual(self._save(self.user, "   ").status_code, 422)
        self.assertEqual(self._save(self.user, "长" * 41).status_code, 422)
        self.assertEqual(self._save(self.user, "长" * 40).status_code, 200)
        self.assertEqual(self._save(self.user, "过头", {"joints": {"leftKnee.bend": 720}}).status_code, 422)
        self.assertEqual(self._save(self.user, "多余", {"joints": {}, "surprise": 1}).status_code, 422)

    def test_delete_is_scoped_to_the_owner(self):
        pose_id = self._save(self.user, "挥手").json()["poses"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/director-desk/poses/{pose_id}", cookies=self._as(self.other)).status_code, 404)
        gone = self.client.delete(f"/api/director-desk/poses/{pose_id}", cookies=self._as(self.user))
        self.assertEqual((gone.status_code, gone.json()["poses"]), (200, []))
        self.assertEqual(self.client.delete(f"/api/director-desk/poses/{pose_id}", cookies=self._as(self.user)).status_code, 404)

    def test_the_library_is_capped(self):
        async def fill():
            for index in range(MAX_DESK_POSES_PER_OWNER):
                await self.store.save_desk_pose(self.user.id, f"姿势{index}", POSE)

        asyncio.run(fill())
        refused = self._save(self.user, "第201个")
        self.assertEqual(refused.status_code, 422)
        self.assertIn("200", refused.json()["detail"])
        # Replacing one of the 200 is still allowed.
        self.assertEqual(self._save(self.user, "姿势0", {"preset": "sit"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
