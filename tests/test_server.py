import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from app.server import make_server
from app.services.allocation.dispatch import seed_allocation


class LocalAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "api.sqlite3"
        self.server = make_server(0, self.db, require_auth=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def get(self, path):
        with urlopen(self.base + path, timeout=5) as response:
            return response.status, json.load(response)

    def post(self, data, path="/api/events", **headers):
        request = Request(self.base + path, data=json.dumps(data).encode(),
                          headers={"Content-Type": "application/json", **headers})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_health_chat_assets_and_retired_paths(self):
        self.assertEqual(self.get("/api/health")[1]["backend"], "offline")
        with urlopen(self.base + "/chat", timeout=5) as response:
            self.assertEqual(response.status, 200)
        with urlopen(self.base + "/", timeout=5) as response:
            self.assertIn(b"/chat", response.read())
        self.assertEqual(self.post({"message": "Allocate ORD-045."}, path="/api/requests")[0], 404)
        self.assertEqual(self.post({"session_id": "s"}, path="/api/sessions")[0], 404)

    def test_lifecycle_api_partial_cancel_reallocate_reassign_complete(self):
        seed_allocation("Allocate ORD-045 to Nimble Needle.", db_path=str(self.db))

        def event(action, **kwargs):
            order = self.get("/api/orders/ORD-045")[1]
            body = {"action": action, "order_id": "ORD-045", "actor": "api-operator",
                    "reason": "Production confirmation", "expected_version": order["version"],
                    "event_id": f"event-{order['version']}", **kwargs}
            status, result = self.post(body, path="/api/events")
            self.assertEqual(status, 200, result)
            return body, result

        body, partial = event("complete", workshop_id="W6", pieces=50)
        self.assertEqual(partial["order"]["completed_pieces"], 50)
        self.assertTrue(self.post(body, path="/api/events")[1]["replayed"])
        event("cancel")
        allocation = seed_allocation("Allocate ORD-045 to Nimble Needle.", db_path=str(self.db),
                                     request_id="realloc")
        self.assertEqual(allocation["result"]["allocation"][0]["pieces"], 100)
        event("reassign", preferred_workshop="W8")
        _, final = event("complete", workshop_id="W8", pieces=100)
        self.assertEqual(final["order"]["state"], "COMPLETED")
        self.assertEqual(len(self.get("/api/orders/ORD-045")[1]["events"]), 4)

    def test_lifecycle_api_rejects_stale_version_and_bad_origin(self):
        seed_allocation("Allocate ORD-045.", db_path=str(self.db))
        body = {"action": "cancel", "order_id": "ORD-045", "actor": "api-operator",
                "reason": "Change allocation", "expected_version": 0, "event_id": "stale"}
        self.assertEqual(self.post(body, path="/api/events")[0], 409)
        self.assertEqual(self.post(body, path="/api/events", Origin="https://example.com")[0], 403)


if __name__ == "__main__":
    unittest.main()
