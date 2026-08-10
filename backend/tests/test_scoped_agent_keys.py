import tempfile
import unittest
from pathlib import Path

from app.repository.studio_repo import StudioRepository
from app.schema.studio import AgentKeyCreateRequest, ProjectCreate


class ScopedAgentKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = StudioRepository(Path(self.temp.name) / "studio.sqlite3")
        self.project = self.repo.create_project("owner-1", ProjectCreate(name="安全代理项目"))

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def test_agent_key_is_scoped_hashed_and_revocable(self):
        issued = self.repo.issue_agent_key(
            self.project.id,
            "owner-1",
            AgentKeyCreateRequest(name="剪辑代理", scopes=["project.read", "artifact.write"]),
        )
        self.assertTrue(issued.token.startswith("sdk_"))
        self.assertNotIn(issued.token, self.repo.debug_agent_key_storage(issued.key.id))
        verified = self.repo.verify_agent_key(issued.token, required_scope="artifact.write")
        self.assertEqual(verified.project_id, self.project.id)
        with self.assertRaises(PermissionError):
            self.repo.verify_agent_key(issued.token, required_scope="provider.submit")
        self.repo.revoke_agent_key(issued.key.id, "owner-1")
        with self.assertRaises(PermissionError):
            self.repo.verify_agent_key(issued.token, required_scope="project.read")

    def test_scoped_external_agent_routes_are_registered(self):
        from app.api.agent_api import router as agent_router
        from app.api.studio_api import router as studio_router

        studio_paths = {route.path for route in studio_router.routes}
        agent_paths = {route.path for route in agent_router.routes}
        self.assertIn("/api/studio/projects/{project_id}/agent-keys", studio_paths)
        self.assertIn("/api/studio/agent-keys/{key_id}", studio_paths)
        self.assertTrue({
            "/api/agent/projects/{project_id}/artifacts",
            "/api/agent/projects/{project_id}/jobs",
            "/api/agent/jobs/{job_id}",
        }.issubset(agent_paths))


if __name__ == "__main__":
    unittest.main()
