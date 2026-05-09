import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from gateway.main import app


class HealthEndpointsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_health_live(self):
        res = self.client.get("/health/live")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body.get("status"), "ok")
        self.assertIn("ts", body)

    def test_health_ready_ok(self):
        res = self.client.get("/health/ready")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body.get("status"), "ready")
        self.assertIn("checks", body)
        self.assertIn("memory", body.get("checks", {}))

    def test_health_ready_missing_key(self):
        with patch("gateway.routers.health_router.get_nvidia_api_key", side_effect=RuntimeError("missing")):
            res = self.client.get("/health/ready")
        self.assertEqual(res.status_code, 503)
        body = res.json()
        self.assertEqual(body.get("status"), "not_ready")
        self.assertFalse(body.get("checks", {}).get("nvidia_api_key", True))


if __name__ == "__main__":
    unittest.main()
