import unittest

from fastapi.testclient import TestClient

from gateway.main import app


class MetricsEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_metrics_endpoint_available(self):
        self.client.get("/v1/models")
        res = self.client.get("/metrics")
        self.assertEqual(res.status_code, 200)
        body = res.text
        self.assertIn("gateway_requests_total", body)
        self.assertIn("gateway_requests_by_path_total", body)


if __name__ == "__main__":
    unittest.main()
