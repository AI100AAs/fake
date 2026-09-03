from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.gizmoapp_server import create_app


ALL_FEATURES = frozenset(
    {"admin", "audio", "machine-learning", "mapping", "optimization", "sample-nodes", "search"}
)


class GizmoAppTestCase(unittest.TestCase):
    def make_app(
        self,
        url_prefix: str = "",
        shell_variant: str = "graphical",
        enabled_features: frozenset[str] = ALL_FEATURES,
        **overrides,
    ):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.sqlite3"
        app = create_app(
            {
                "TESTING": True,
                "DB_PATH": db_path,
                "URL_PREFIX": url_prefix,
                "SECRET_KEY": "test-secret",
                "AUTO_MIGRATE": True,
                "ENABLED_FEATURES": enabled_features,
                **overrides,
            },
            shell_variant=shell_variant,
        )
        return app

    def tearDown(self):
        temp_dir = getattr(self, "temp_dir", None)
        if temp_dir is not None:
            temp_dir.cleanup()

    def test_bootstrap_and_readiness_use_prefix(self):
        app = self.make_app("/demo-app")
        client = app.test_client()

        bootstrap = client.get("/demo-app/api/bootstrap")
        ready = client.get("/demo-app/readyz")

        self.assertEqual(bootstrap.status_code, 200)
        self.assertEqual(bootstrap.get_json()["app"]["shell"], "graphical")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.get_json()["status"], "ready")
        self.assertEqual(ready.get_json()["schemaVersion"], 3)

    def test_optional_routes_are_disabled_by_default(self):
        app = self.make_app(enabled_features=frozenset())
        client = app.test_client()

        self.assertEqual(client.get("/admin/").status_code, 404)
        response = client.post("/api/audio/analyze", json={"samples": [0], "sampleRate": 1})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content_type, "application/json")
        statuses = {
            item["slug"]: item["status"]
            for item in client.get("/api/capabilities").get_json()["capabilities"]
        }
        self.assertEqual(statuses["audio"], "disabled")
        self.assertEqual(statuses["mapping"], "disabled")

    def test_pwa_routes_are_not_exposed(self):
        app = self.make_app("/demo-app")
        client = app.test_client()

        self.assertEqual(client.get("/demo-app/manifest.webmanifest").status_code, 404)
        self.assertEqual(client.get("/demo-app/sw.js").status_code, 404)

    def test_can_insert_and_search_sample_node(self):
        app = self.make_app()
        client = app.test_client()
        response = client.post(
            "/api/sample-nodes",
            json={
                "slug": "compass",
                "label": "Compass",
                "description": "Created by the test suite.",
                "accent_color": "#72d1c2",
                "x": 0.6,
                "y": 0.4,
                "radius": 0.12,
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["sampleNode"]["slug"], "compass")
        search = client.get("/api/search?q=compass")
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.get_json()["results"][0]["slug"], "compass")

    def test_json_endpoints_reject_non_object_json(self):
        app = self.make_app()
        client = app.test_client()

        for path in ("/api/sample-nodes", "/api/audio/analyze", "/api/optimize/route"):
            with self.subTest(path=path):
                response = client.post(path, json=[1])
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.content_type, "application/json")
                self.assertIn("must be an object", response.get_json()["errors"][0])

    def test_json_endpoints_require_json_content_type(self):
        app = self.make_app()
        response = app.test_client().post("/api/audio/analyze", data="samples=1")

        self.assertEqual(response.status_code, 415)
        self.assertIn("application/json", response.get_json()["errors"][0])

    def test_non_finite_and_wrong_type_values_are_rejected(self):
        app = self.make_app()
        client = app.test_client()

        route = client.post(
            "/api/optimize/route",
            json={"points": [{"id": "a", "x": "nan", "y": 0}, {"id": "b", "x": 1, "y": 1}]},
        )
        audio = client.post("/api/audio/analyze", json={"samples": ["nan"], "sampleRate": 1})
        sample = client.post("/api/sample-nodes", json={"slug": "obj-label", "label": {"bad": True}})

        self.assertEqual(route.status_code, 400)
        self.assertEqual(audio.status_code, 400)
        self.assertEqual(sample.status_code, 400)
        self.assertNotIn("NaN", route.get_data(as_text=True))

    def test_payload_size_limit_returns_json(self):
        app = self.make_app(MAX_CONTENT_LENGTH=16_384)
        response = app.test_client().post(
            "/api/audio/analyze",
            data='{"samples":["' + ("1" * 20_000) + '"]}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.content_type, "application/json")

    def test_capability_endpoints_validate_and_respond(self):
        app = self.make_app()
        client = app.test_client()

        audio = client.post("/api/audio/analyze", json={"samples": [0, 0.5, -0.5, 0], "sampleRate": 4})
        route = client.post(
            "/api/optimize/route",
            json={"points": [{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 1, "y": 0}]},
        )
        mapping = client.get("/api/map/default")
        ml_status = client.get("/api/ml/status")
        invalid_ml = client.post("/api/ml/kmeans", json={"clusters": "nope", "points": [[0, 0], [1, 1]]})

        self.assertEqual(audio.status_code, 200)
        self.assertAlmostEqual(audio.get_json()["durationSeconds"], 1.0)
        self.assertEqual(route.get_json()["orderedIds"], ["a", "b"])
        self.assertEqual(mapping.get_json()["defaultLocation"]["label"], "UBC Vancouver")
        self.assertIn("available", ml_status.get_json())
        self.assertEqual(invalid_ml.status_code, 400)

    def test_response_hardening_and_request_id(self):
        app = self.make_app()
        response = app.test_client().get("/api/bootstrap")

        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertRegex(response.headers["X-Request-ID"], r"^[0-9a-f]{16}$")

    def test_graphical_and_text_shells_include_error_boundary(self):
        for shell in ("graphical", "text"):
            with self.subTest(shell=shell):
                app = self.make_app(shell_variant=shell)
                html = app.test_client().get("/").get_data(as_text=True)
                self.assertIn('id="app-error"', html)
                self.assertIn("boot.js", html)
                self.assertNotIn("manifest.webmanifest", html)
                self.tearDown()

    def test_error_boundary_ignores_benign_resize_observer_notifications(self):
        boot_source = (
            Path(__file__).parents[1]
            / "server"
            / "gizmoapp_server"
            / "static"
            / "app"
            / "boot.js"
        ).read_text(encoding="utf-8")

        self.assertIn("ResizeObserver loop limit exceeded", boot_source)
        self.assertIn("ResizeObserver loop completed with undelivered notifications.", boot_source)
        self.assertIn("event.preventDefault()", boot_source)

    def test_admin_is_available_only_when_enabled(self):
        app = self.make_app(enabled_features=frozenset({"admin"}))
        response = app.test_client().get("/admin/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Deployment-facing details", response.get_data(as_text=True))

    def test_pasted_article_is_sent_to_course_model(self):
        app = self.make_app()
        article = "A pasted story makes a checkable claim about a new study and its reported results."
        report = {"score": 70, "label": "Needs verification", "summary": "Check it.", "claims": [], "signals": []}

        with patch("server.gizmoapp_server.api._llm_report", return_value=report) as llm_report:
            response = app.test_client().post("/api/analyze", json={"articleText": article})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["articleText"], article)
        llm_report.assert_called_once_with(article, "")

    def test_article_history_is_isolated_by_owner_token(self):
        app = self.make_app()
        client = app.test_client()
        first_token = client.get("/api/bootstrap").get_json()["historyOwnerToken"]
        second_token = client.get("/api/bootstrap").get_json()["historyOwnerToken"]
        payload = {"inputType": "text", "articleText": "Private story for the first user.", "report": {"score": 91}}

        saved = client.post("/api/history", headers={"X-History-Owner": first_token}, json=payload)
        first_history = client.get("/api/history", headers={"X-History-Owner": first_token})
        second_history = client.get("/api/history", headers={"X-History-Owner": second_token})
        missing_token = client.get("/api/history")

        self.assertEqual(saved.status_code, 201)
        self.assertEqual(len(first_history.get_json()["history"]), 1)
        self.assertEqual(second_history.get_json()["history"], [])
        self.assertEqual(missing_token.status_code, 401)

    def test_evidence_desk_receives_section_two_assessment(self):
        app = self.make_app()
        report = {
            "score": 78,
            "label": "Mostly credible",
            "summary": "The main claim is plausible but needs verification.",
            "claims": [{"claim": "The study found an improvement.", "assessment": "supported", "evidence": "The article reports the study result but gives limited methodology."}],
            "signals": [{"kind": "Missing context", "text": "The sample size is not stated.", "tone": "caution"}],
        }

        with patch("server.gizmoapp_server.api.ask", return_value="The score reflects the mixed evidence.") as ask:
            response = app.test_client().post(
                "/api/chat",
                json={"message": "Why did you give this 78/100?", "articleText": "The study found an improvement.", "report": report},
            )

        self.assertEqual(response.status_code, 200)
        prompt = ask.call_args.args[0]
        self.assertIn("78", prompt)
        self.assertIn("actual assessment previously produced by the SignalCheck course model", prompt)
        self.assertIn("model's recorded result", prompt)
        self.assertIn("The main claim is plausible but needs verification.", prompt)
        self.assertIn("limited methodology", prompt)


if __name__ == "__main__":
    unittest.main()
