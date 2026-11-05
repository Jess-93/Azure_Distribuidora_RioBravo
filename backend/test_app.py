import tempfile
import unittest
import ipaddress
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from uuid import uuid4

from azure.core.exceptions import ClientAuthenticationError
from fastapi.testclient import TestClient

from backend import app as backend_app
from backend.app import app
from backend.inventory import normalize_inventory_query


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_clean_foundry_citations_removes_file_and_legacy_markers(self):
        answer = (
            "La respuesta está aquí. "
            "\ue200filecite\ue202turn4file0\ue202turn4file2\ue201 "
            ""
        )

        self.assertEqual(backend_app.clean_foundry_citations(answer), "La respuesta está aquí.")

    def test_clean_foundry_citations_removes_truncated_file_marker(self):
        answer = "La respuesta está aquí. \ue200filecite\ue202turn4file0"

        self.assertEqual(backend_app.clean_foundry_citations(answer), "La respuesta está aquí.")

    def test_clean_foundry_citations_removes_page_range_citation(self):
        answer = (
            "¿Quieres que prosiga con este trámite?\n\n"
            "【15:3-5†Politica de Devoluciones - Distribuidora Rio Claro.pdf】"
        )

        self.assertEqual(
            backend_app.clean_foundry_citations(answer),
            "¿Quieres que prosiga con este trámite?",
        )

    def test_clean_foundry_citations_removes_indexed_file_markers(self):
        answer = (
            "La respuesta incluye la [ADM] correspondiente.\n"
            "Fuente: Política de Devoluciones 【0:catalogo_skus.txt】 "
            "[1:Politica_Devoluciones.pdf] "
        )

        self.assertEqual(
            backend_app.clean_foundry_citations(answer),
            "La respuesta incluye la [ADM] correspondiente.\n"
            "Fuente: Política de Devoluciones",
        )

    def test_inventory_agent_initialization_does_not_skip_customer_agent_client(self):
        project = SimpleNamespace(
            get_openai_client=Mock(side_effect=["inventory-client", "customer-client"])
        )

        with (
            patch.object(backend_app, "PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/project"),
            patch.object(
                backend_app,
                "INVENTORY_AGENT_ENDPOINT",
                "https://example.services.ai.azure.com/api/projects/project/agents/warehouse/endpoint",
            ),
            patch.object(backend_app, "AGENT_NAME", "CustomerAgent"),
            patch.object(backend_app, "foundry_project", None),
            patch.object(backend_app, "foundry_openai_client", None),
            patch.object(backend_app, "inventory_openai_client", None),
            patch.object(backend_app, "AIProjectClient", return_value=project),
            patch.object(backend_app, "DefaultAzureCredential"),
        ):
            inventory_client = backend_app.get_inventory_foundry_client()
            _, customer_client = backend_app.get_foundry_clients()

        self.assertEqual(inventory_client, "inventory-client")
        self.assertEqual(customer_client, "customer-client")
        self.assertEqual(
            project.get_openai_client.call_args_list[0].kwargs["agent_name"],
            "warehouse",
        )
        self.assertEqual(
            project.get_openai_client.call_args_list[1].kwargs["agent_name"],
            "CustomerAgent",
        )

    def test_chat_adapts_request_and_foundry_text(self):
        openai_client = SimpleNamespace(
            responses=SimpleNamespace(
                create=Mock(
                    side_effect=[
                        SimpleNamespace(
                            id="response-1",
                            output_text=(
                                "Fuente: Política de Devoluciones - Distribuidora Río Claro "
                                ",  "
                                "\ue200filecite\ue202turn4file0\ue202turn4file2\ue201"
                            ),
                            output=[
                                {
                                    "content": [
                                        {
                                            "annotations": [
                                                {
                                                    "type": "file_citation",
                                                    "filename": "Politica.pdf",
                                                    "page_number": 2,
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ],
                        ),
                        SimpleNamespace(id="response-2", output_text="Segunda respuesta", output=[]),
                    ],
                )
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(backend_app, "SESSION_DB_PATH", backend_app.Path(temp_dir) / "sessions.sqlite3"),
                patch("backend.app.get_foundry_clients", return_value=(object(), openai_client)),
            ):
                backend_app.initialize_session_store()
                session_id = str(uuid4())
                request = {
                    "message": "¿Cómo hago una devolución?",
                    "sessionId": session_id,
                    "context": {"branch": "León", "role": "Cliente"},
                }
                response = self.client.post("/api/chat", json=request)
                second_response = self.client.post(
                    "/api/chat",
                    json={**request, "message": "¿Y si está abierto?"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "response": "Fuente: Política de Devoluciones - Distribuidora Río Claro",
                "sources": [
                    {
                        "title": "Politica.pdf",
                        "section": "Documento consultado",
                        "page": 2,
                    }
                ],
                "escalateToHuman": False,
            },
        )
        self.assertEqual(
            openai_client.responses.create.call_args_list[0].kwargs,
            {"input": "Sucursal: León\nPerfil: Cliente\n\nConsulta: ¿Cómo hago una devolución?"},
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.json()["response"], "Segunda respuesta")
        self.assertEqual(
            openai_client.responses.create.call_args_list[1].kwargs,
            {
                "input": "Sucursal: León\nPerfil: Cliente\n\nConsulta: ¿Y si está abierto?",
                "previous_response_id": "response-1",
            },
        )

    def test_chat_rejects_invalid_session_identifier(self):
        response = self.client.post(
            "/api/chat",
            json={"message": "Hola", "sessionId": "x" * 36},
        )

        self.assertEqual(response.status_code, 422)

    def test_chat_surfaces_missing_server_configuration(self):
        with patch(
            "backend.app.get_foundry_clients",
            side_effect=RuntimeError("Foundry is not configured"),
        ):
            response = self.client.post(
                "/api/chat",
                json={"message": "Hola", "sessionId": str(uuid4())},
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("No fue posible obtener una respuesta de Foundry", response.json()["detail"])

    def test_chat_explains_missing_azure_credentials(self):
        with patch(
            "backend.app.get_foundry_clients",
            side_effect=ClientAuthenticationError("No Azure CLI credential available"),
        ):
            response = self.client.post(
                "/api/chat",
                json={"message": "Hola", "sessionId": str(uuid4())},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("instala Azure CLI", response.json()["detail"])
        self.assertIn("az login", response.json()["detail"])

    def test_migrates_old_foundry_session_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = backend_app.Path(temp_dir) / "sessions.sqlite3"
            with patch.object(backend_app, "SESSION_DB_PATH", db_path):
                with backend_app.session_database() as connection:
                    connection.execute(
                        """
                        CREATE TABLE chat_sessions (
                            client_session_id TEXT PRIMARY KEY,
                            foundry_session_id TEXT NOT NULL,
                            updated_at INTEGER NOT NULL
                        )
                        """
                    )
                backend_app.initialize_session_store()
                with backend_app.session_database() as connection:
                    columns = {
                        row[1] for row in connection.execute("PRAGMA table_info(chat_sessions)").fetchall()
                    }

        self.assertIn("previous_response_id", columns)
        self.assertNotIn("foundry_session_id", columns)


class SpeechTokenApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        backend_app.speech_request_times_by_client.clear()
        backend_app.speech_global_request_times.clear()

    def test_returns_temporary_token_and_no_store_headers(self):
        fake_key = "test-key-not-a-real-credential"
        response_body = BytesIO(b"temporary-speech-token")
        with (
            patch.object(backend_app, "SPEECH_KEY", fake_key),
            patch.object(backend_app, "SPEECH_REGION", "eastus"),
            patch("backend.app.urlopen", return_value=response_body) as mocked_urlopen,
        ):
            response = self.client.get("/api/speech/token")

        self.assertEqual(
            response.json(),
            {"token": "temporary-speech-token", "region": "eastus"},
        )
        self.assertEqual(mocked_urlopen.call_args.kwargs["timeout"], 5)
        upstream_request = mocked_urlopen.call_args.args[0]
        self.assertEqual(upstream_request.full_url, "https://eastus.api.cognitive.microsoft.com/sts/v1.0/issueToken")
        self.assertEqual(upstream_request.get_method(), "POST")
        self.assertEqual(upstream_request.get_header("Ocp-apim-subscription-key"), fake_key)
        self.assertNotIn(fake_key, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store, private")
        self.assertEqual(response.headers["pragma"], "no-cache")

    def test_missing_configuration_returns_service_unavailable(self):
        with (
            patch.object(backend_app, "SPEECH_KEY", ""),
            patch.object(backend_app, "SPEECH_REGION", ""),
        ):
            response = self.client.get("/api/speech/token")

        self.assertEqual(response.status_code, 503)
        self.assertIn("AZURE_SPEECH_KEY", response.json()["detail"])
        self.assertEqual(response.headers["cache-control"], "no-store, private")

    def test_rejects_malformed_region_without_upstream_call(self):
        with (
            patch.object(backend_app, "SPEECH_KEY", "dummy"),
            patch.object(backend_app, "SPEECH_REGION", "eastus.example.com"),
            patch("backend.app.urlopen") as mocked_urlopen,
        ):
            response = self.client.get("/api/speech/token")

        self.assertEqual(response.status_code, 503)
        mocked_urlopen.assert_not_called()

    def test_upstream_http_error_does_not_leak_details(self):
        error = HTTPError("https://speech.invalid", 401, "unauthorized", None, None)
        with (
            patch.object(backend_app, "SPEECH_KEY", "dummy"),
            patch.object(backend_app, "SPEECH_REGION", "eastus"),
            patch("backend.app.urlopen", side_effect=error),
        ):
            response = self.client.get("/api/speech/token")

        self.assertEqual(response.status_code, 502)
        self.assertNotIn("dummy", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store, private")

    def test_upstream_timeout_returns_gateway_timeout(self):
        with (
            patch.object(backend_app, "SPEECH_KEY", "dummy"),
            patch.object(backend_app, "SPEECH_REGION", "eastus"),
            patch("backend.app.urlopen", side_effect=TimeoutError()),
        ):
            response = self.client.get("/api/speech/token")

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.headers["cache-control"], "no-store, private")

    def test_upstream_network_error_returns_bad_gateway(self):
        with (
            patch.object(backend_app, "SPEECH_KEY", "dummy"),
            patch.object(backend_app, "SPEECH_REGION", "eastus"),
            patch("backend.app.urlopen", side_effect=URLError("connection failed")),
        ):
            response = self.client.get("/api/speech/token")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.headers["cache-control"], "no-store, private")

    def test_empty_upstream_body_is_an_explicit_error(self):
        with (
            patch.object(backend_app, "SPEECH_KEY", "dummy"),
            patch.object(backend_app, "SPEECH_REGION", "eastus"),
            patch("backend.app.urlopen", return_value=BytesIO(b" \n")),
        ):
            response = self.client.get("/api/speech/token")

        self.assertEqual(response.status_code, 502)

    def test_speech_endpoint_has_independent_per_client_rate_limit(self):
        with (
            patch.object(backend_app, "SPEECH_REQUESTS_PER_MINUTE", 1),
            patch.object(backend_app, "SPEECH_GLOBAL_REQUESTS_PER_MINUTE", 10),
            patch.object(backend_app, "SPEECH_KEY", ""),
            patch.object(backend_app, "SPEECH_REGION", ""),
        ):
            first_response = self.client.get("/api/speech/token")
            second_response = self.client.get("/api/speech/token")

        self.assertEqual(first_response.status_code, 503)
        self.assertEqual(second_response.status_code, 429)

    def test_untrusted_peer_cannot_choose_rate_limit_identity_with_forwarded_header(self):
        request = backend_app.Request(
            {
                "type": "http",
                "headers": [(b"x-forwarded-for", b"203.0.113.10")],
                "client": ("198.51.100.20", 12345),
            }
        )
        with patch.object(backend_app, "SPEECH_TRUSTED_PROXY_CIDRS", (ipaddress.ip_network("10.0.0.0/8"),)):
            self.assertEqual(backend_app.get_speech_client_ip(request), "198.51.100.20")

    def test_trusted_proxy_chain_resolves_nearest_untrusted_client(self):
        request = backend_app.Request(
            {
                "type": "http",
                "headers": [(b"x-forwarded-for", b"192.0.2.99, 203.0.113.15, 10.1.2.3")],
                "client": ("10.2.3.4", 12345),
            }
        )
        with patch.object(backend_app, "SPEECH_TRUSTED_PROXY_CIDRS", (ipaddress.ip_network("10.0.0.0/8"),)):
            self.assertEqual(backend_app.get_speech_client_ip(request), "203.0.113.15")

    def test_unconfigured_proxy_trust_ignores_forwarded_header(self):
        request = backend_app.Request(
            {
                "type": "http",
                "headers": [(b"x-forwarded-for", b"203.0.113.10")],
                "client": ("10.1.2.3", 12345),
            }
        )
        with patch.object(backend_app, "SPEECH_TRUSTED_PROXY_CIDRS", ()):
            self.assertEqual(backend_app.get_speech_client_ip(request), "10.1.2.3")


class InventoryApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.inventory_path = backend_app.Path(self.temp_dir.name) / "inventario.csv"
        self.addCleanup(self.temp_dir.cleanup)
        self.config_patches = [
            patch.object(backend_app, "INVENTORY_USERNAME", "Almacén1"),
            patch.object(backend_app, "INVENTORY_PASSWORD", "inventory-test-only-password"),
            patch.object(backend_app, "INVENTORY_AUTH_SECRET", "test-secret-" + "x" * 48),
        ]
        for config_patch in self.config_patches:
            config_patch.start()
            self.addCleanup(config_patch.stop)
        backend_app.inventory_login_request_times_by_client.clear()
        backend_app.inventory_login_global_request_times.clear()
        self.access_token = backend_app.encode_inventory_token(
            "Almacén1",
            int(backend_app.time.time()) + backend_app.INVENTORY_TOKEN_TTL_SECONDS,
        )

    def write_inventory(self, contents):
        self.inventory_path.write_text(contents, encoding="utf-8")

    def query_inventory(self, query):
        with patch.object(backend_app, "INVENTORY_CSV_PATH", self.inventory_path):
            return self.client.post(
                "/api/inventory/query",
                json={"query": query},
                headers={"Authorization": f"Bearer {self.access_token}"},
            )

    def chat_inventory(self, query, session_id):
        with patch.object(backend_app, "INVENTORY_CSV_PATH", self.inventory_path):
            return self.client.post(
                "/api/inventory/chat",
                json={"query": query, "sessionId": session_id},
                headers={"Authorization": "Bearer " + self.access_token},
            )

    def test_inventory_chat_uses_existing_inventory_access_and_returns_inventory_mode_without_agent(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "CL-001,Cloro,1 litro,,18,piezas,2026-11-02\n"
        )

        with patch.object(backend_app, "INVENTORY_AGENT_ENDPOINT", ""):
            response = self.chat_inventory("¿Cuánto cloro queda?", str(uuid4()))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "inventory")
        self.assertIsNone(response.json()["assistantResponse"])
        self.assertEqual(response.json()["result"]["status"], "found")
        self.assertEqual(response.json()["result"]["item"]["sku"], "CL-001")

    def test_inventory_chat_passes_only_the_current_inventory_result_to_foundry(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado,precio_mxn\n"
            "CL-001,Cloro,1 litro,,18,piezas,2026-11-02,349.50\n"
        )
        openai_client = SimpleNamespace(
            responses=SimpleNamespace(
                create=Mock(side_effect=[
                    SimpleNamespace(id="inventory-response-1", output_text="Hay 18 piezas."),
                    SimpleNamespace(id="inventory-response-2", output_text="El SKU es CL-001."),
                ])
            )
        )
        session_id = str(uuid4())

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(backend_app, "SESSION_DB_PATH", backend_app.Path(temp_dir) / "sessions.sqlite3"),
                patch.object(
                    backend_app,
                    "INVENTORY_AGENT_ENDPOINT",
                    "https://example.services.ai.azure.com/api/projects/project/agents/warehouse/endpoint/protocols/openai",
                ),
                patch.object(
                    backend_app,
                    "PROJECT_ENDPOINT",
                    "https://example.services.ai.azure.com/api/projects/project",
                ),
                patch.object(backend_app, "get_inventory_foundry_client", return_value=openai_client),
                patch.object(backend_app, "INVENTORY_CSV_PATH", self.inventory_path),
            ):
                backend_app.initialize_session_store()
                first_response = self.client.post(
                    "/api/inventory/chat",
                    json={"query": "¿Cuánto cloro queda?", "sessionId": session_id},
                    headers={"Authorization": "Bearer " + self.access_token},
                )
                second_response = self.client.post(
                    "/api/inventory/chat",
                    json={"query": "¿Cuál es su SKU?", "sessionId": session_id},
                    headers={"Authorization": "Bearer " + self.access_token},
                )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.json()["mode"], "agent")
        self.assertEqual(first_response.json()["assistantResponse"], "Hay 18 piezas.")
        prompt = openai_client.responses.create.call_args_list[0].kwargs["input"]
        self.assertIn('"sku": "CL-001"', prompt)
        self.assertIn('"available": "18"', prompt)
        self.assertNotIn('"priceMxn"', prompt)
        self.assertEqual(
            openai_client.responses.create.call_args_list[1].kwargs["previous_response_id"],
            "inventory-response-1",
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.json()["assistantResponse"], "El SKU es CL-001.")

    def test_inventory_chat_requires_the_existing_inventory_login(self):
        response = self.client.post(
            "/api/inventory/chat",
            json={"query": "Hola", "sessionId": str(uuid4())},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Inicia sesión para consultar el inventario.")

    def test_returns_exact_available_stock_for_product_and_presentation(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "CL-001,Cloro,1 litro,cloro de litro; cloro líquido,18,piezas,2026-11-02\n"
        )

        response = self.query_inventory("¿Cuánto cloro de litro nos queda?")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "found",
                "item": {
                    "sku": "CL-001",
                    "product": "Cloro",
                    "presentation": "1 litro",
                    "available": "18",
                    "unit": "piezas",
                    "updatedAt": "2026-11-02",
                },
                "requestedFields": ["available"],
            },
        )
        self.assertEqual(response.headers["cache-control"], "no-store, private")

    def test_returns_only_requested_fields_for_sku_follow_up_questions(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado,precio_mxn\n"
            "SKU-1005,Jabones,12 piezas,,20,paquetes,2026-11-02,279.00\n"
        )

        response = self.query_inventory(
            "¿Qué fecha es la actualización? ¿Tiene el SKU 1005?"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "found")
        self.assertEqual(payload["requestedFields"], ["updatedAt", "exists"])
        self.assertEqual(payload["item"]["sku"], "SKU-1005")

    def test_recognizes_individual_product_information_requests(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado,precio_mxn\n"
            "SKU-1005,Jabones,12 piezas,,20,paquetes,2026-11-02,279.00\n"
        )

        cases = (
            ("Solo el precio del SKU 1005", ["priceMxn"]),
            ("Solo el producto del SKU 1005", ["product"]),
            ("Solo la presentación del SKU 1005", ["presentation"]),
            ("Dime el SKU del producto 1005", ["sku"]),
        )
        for query, expected_fields in cases:
            with self.subTest(query=query):
                response = self.query_inventory(query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["requestedFields"], expected_fields)

    def test_returns_price_only_when_explicitly_requested(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado,precio_mxn\n"
            "CL-001,Cloro,1 litro,cloro de litro,18,piezas,2026-11-02,349.50\n"
        )

        stock_response = self.query_inventory("¿Cuánto cloro de litro nos queda?")
        price_response = self.query_inventory("¿Cuál es el precio del cloro de litro?")

        self.assertEqual(stock_response.status_code, 200)
        self.assertNotIn("priceMxn", stock_response.json()["item"])
        self.assertNotIn("priceRequested", stock_response.json())
        self.assertEqual(price_response.status_code, 200)
        self.assertTrue(price_response.json()["priceRequested"])
        self.assertEqual(price_response.json()["item"]["priceMxn"], "349.50")

    def test_rejects_invalid_inventory_price(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado,precio_mxn\n"
            "CL-001,Cloro,1 litro,cloro de litro,18,piezas,2026-11-02,no-es-precio\n"
        )

        response = self.query_inventory("¿Cuál es el precio del cloro de litro?")

        self.assertEqual(response.status_code, 503)
        self.assertIn("no es un número válido", response.json()["detail"])

    def test_returns_top_ten_inventory_codes_separately_by_unit(self):
        rows = [
            f"SKU-{index:04d},Producto {index},1 pieza,,{index},piezas,2026-11-02"
            for index in range(1, 13)
        ]
        rows.extend([
            "PK-001,Paquete A,1 paquete,,8,paquetes,2026-11-02",
            "PK-002,Paquete B,1 paquete,,3,paquetes,2026-11-02",
            "JG-001,Juego A,1 juego,,5,juegos,2026-11-02",
        ])
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            + "\n".join(rows)
            + "\n"
        )

        response = self.query_inventory("Río, dame los 10 códigos con más existencias")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ranking")
        self.assertEqual(payload["limit"], 10)
        groups = {group["unit"]: group["items"] for group in payload["groups"]}
        self.assertEqual(set(groups), {"piezas", "paquetes", "juegos"})
        self.assertEqual(len(groups["piezas"]), 10)
        self.assertEqual(
            [item["available"] for item in groups["piezas"]],
            ["12", "11", "10", "9", "8", "7", "6", "5", "4", "3"],
        )
        self.assertEqual(
            [item["sku"] for item in groups["paquetes"]],
            ["PK-001", "PK-002"],
        )
        self.assertEqual(groups["juegos"][0]["sku"], "JG-001")

    def test_returns_highest_inventory_per_unit_and_includes_ties(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "PC-001,Pieza A,1 pieza,,20,piezas,2026-11-02\n"
            "PC-002,Pieza B,1 pieza,,20,piezas,2026-11-02\n"
            "PC-003,Pieza C,1 pieza,,10,piezas,2026-11-02\n"
            "PK-001,Paquete A,1 paquete,,7,paquetes,2026-11-02\n"
            "JG-001,Juego A,1 juego,,4,juegos,2026-11-02\n"
        )

        response = self.query_inventory("Río, cuál es el código con más inventario")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ranking")
        self.assertEqual(payload["limit"], 1)
        groups = {group["unit"]: group["items"] for group in payload["groups"]}
        self.assertEqual({group: len(items) for group, items in groups.items()}, {
            "piezas": 2,
            "paquetes": 1,
            "juegos": 1,
        })
        self.assertEqual([item["sku"] for item in groups["piezas"]], ["PC-001", "PC-002"])

    def test_returns_requested_products_ranked_by_highest_price(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado,precio_mxn\n"
            "PC-001,Producto A,1 pieza,,20,piezas,2026-11-02,1200.00\n"
            "PC-002,Producto B,1 pieza,,15,piezas,2026-11-02,4500.00\n"
            "PC-003,Producto C,1 pieza,,10,piezas,2026-11-02,2500.00\n"
            "PC-004,Producto D,1 pieza,,5,piezas,2026-11-02,900.00\n"
            "PC-005,Producto E,1 pieza,,4,piezas,2026-11-02,1800.00\n"
            "PC-006,Producto F,1 pieza,,3,piezas,2026-11-02,3200.00\n"
        )

        response = self.query_inventory("Río dame los 5 números con mayor precio por favor")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ranking")
        self.assertEqual(payload["rankingBy"], "price")
        self.assertTrue(payload["priceRequested"])
        items = payload["groups"][0]["items"]
        self.assertEqual([item["sku"] for item in items], [
            "PC-002", "PC-006", "PC-003", "PC-005", "PC-001",
        ])
        self.assertEqual([item["priceMxn"] for item in items], [
            "4500.00", "3200.00", "2500.00", "1800.00", "1200.00",
        ])

    def test_price_ranking_reports_when_inventory_has_no_prices(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "PC-001,Producto A,1 pieza,,20,piezas,2026-11-02\n"
        )

        response = self.query_inventory("Dame los 5 productos con mayor precio")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "no_prices"})

    def test_returns_complete_inventory_and_unit_totals_for_total_stock_request(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "PC-001,Licuadora,1 pieza,,20,piezas,2026-11-02\n"
            "PC-002,Plancha,1 pieza,,12,piezas,2026-11-02\n"
            "PK-001,Jabones,1 paquete,,7,paquetes,2026-11-02\n"
            "JG-001,Cuchillos,1 juego,,4,juegos,2026-11-02\n"
        )

        response = self.query_inventory("¿Río, puedes darme la lista total de existencias? Por favor")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "inventory_list")
        groups = {group["unit"]: group for group in payload["groups"]}
        self.assertEqual(set(groups), {"piezas", "paquetes", "juegos"})
        self.assertEqual((groups["piezas"]["total"], groups["piezas"]["count"]), ("32", 2))
        self.assertEqual((groups["paquetes"]["total"], groups["paquetes"]["count"]), ("7", 1))
        self.assertEqual((groups["juegos"]["total"], groups["juegos"]["count"]), ("4", 1))
        self.assertEqual(len(groups["piezas"]["items"]), 2)

    def test_returns_complete_catalog_for_catalog_request(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "PC-001,Licuadora,1 pieza,,20,piezas,2026-11-02\n"
            "PK-001,Jabones,1 paquete,,7,paquetes,2026-11-02\n"
        )

        response = self.query_inventory("¿Río, puedes darme todo el catálogo? Por favor")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "inventory_list")
        items = [item for group in payload["groups"] for item in group["items"]]
        self.assertEqual({item["sku"] for item in items}, {"PC-001", "PK-001"})

    def test_understands_inventory_list_requests_with_plural_variants(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "PC-001,Licuadora,1 pieza,,20,piezas,2026-11-02\n"
            "PK-001,Jabones,1 paquete,,7,paquetes,2026-11-02\n"
        )

        for phrase in (
            "Dame la lista de los inventarios, por favor.",
            "Dame todas las existencias, por favor.",
            "Muestra el listado completo de productos del inventario.",
        ):
            with self.subTest(phrase=phrase):
                response = self.query_inventory(phrase)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "inventory_list")
                items = [
                    item
                    for group in response.json()["groups"]
                    for item in group["items"]
                ]
                self.assertEqual({item["sku"] for item in items}, {"PC-001", "PK-001"})

    def test_inventory_demo_questions_are_supported_by_catalog_search(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado,precio_mxn\n"
            "SKU-1001,Purificador PureFlow,1 pieza,purificador; linea blanca,20,piezas,2026-11-02,1200.00\n"
            "SKU-1002,Microondas SoloCook,20 litros,microondas; linea blanca,24,piezas,2026-11-02,2200.00\n"
            "SKU-1003,Olla SlowCook,1 pieza,olla; linea blanca,14,piezas,2026-11-02,1100.00\n"
            "SKU-1004,Plancha FastSteam,1 pieza,plancha,44,piezas,2026-11-02,399.00\n"
            "SKU-1005,Licuadora ECO,1 pieza,licuadora,37,piezas,2026-11-02,649.00\n"
            "SKU-1006,Escoba hogar,1 pieza,escoba,13,piezas,2026-11-02,189.00\n"
            "SKU-1007,Parrilla eléctrica,1 pieza,parrilla; linea blanca,29,piezas,2026-11-02,1399.00\n"
            "SKU-1008,Cafetera AromaPlus,1 pieza,cafetera; aromaplus,6,piezas,2026-11-02,729.00\n"
        )
        questions_and_statuses = (
            ("¿Cuánta existencia hay del SKU-1001?", "found"),
            ("¿Qué precio tiene el SKU-1002?", "found"),
            ("¿Qué producto corresponde al SKU-1003?", "found"),
            ("¿Qué presentación tiene el SKU-1004?", "found"),
            ("¿Qué fecha de actualización tiene el SKU-1005?", "found"),
            ("¿Qué hay en Línea Blanca?", "ambiguous"),
            ("Dame los 3 productos con más existencias.", "ranking"),
            ("Dame los 3 productos con precio más alto.", "ranking"),
            ("Muestra el catálogo completo.", "inventory_list"),
            ("Dame 3 productos al azar.", "random_selection"),
            ("Dame los inventarios de licuadoras, escobas, parrillas y Línea Blanca.", "multiple_matches"),
            ("¿Cuánto cuesta y cuántas unidades hay de la cafetera AromaPlus?", "found"),
        )

        for question, expected_status in questions_and_statuses:
            with self.subTest(question=question):
                response = self.query_inventory(question)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], expected_status)

    def test_inventory_list_intent_does_not_override_product_search(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "PC-001,Licuadora,1 pieza,,20,piezas,2026-11-02\n"
            "PK-001,Jabones,1 paquete,,7,paquetes,2026-11-02\n"
        )

        response = self.query_inventory("Dame el inventario de licuadoras")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "found")
        self.assertEqual(response.json()["item"]["sku"], "PC-001")

    def test_understands_spoken_sku_variants_in_full_list_request(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "PC-001,Licuadora,1 pieza,,20,piezas,2026-11-02\n"
            "PK-001,Jabones,1 paquete,,7,paquetes,2026-11-02\n"
        )

        for phrase in (
            "Río dame una lista de todos los scuare, por favor",
            "Río dame la lista de los Skaw, por favor",
            "Río dame la lista de los Square, por favor, envía mensaje",
        ):
            with self.subTest(phrase=phrase):
                response = self.query_inventory(phrase)
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "inventory_list")
                items = [item for group in payload["groups"] for item in group["items"]]
                self.assertEqual({item["sku"] for item in items}, {"PC-001", "PK-001"})

    def test_understands_merchandise_as_full_inventory_list_request(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "PC-001,Licuadora,1 pieza,,20,piezas,2026-11-02\n"
            "PK-001,Jabones,1 paquete,,7,paquetes,2026-11-02\n"
        )

        response = self.query_inventory("Río dame, una lista de las mercancías, por favor")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "inventory_list")
        items = [item for group in payload["groups"] for item in group["items"]]
        self.assertEqual(len(items), 2)

    def test_corrects_spoken_sku_prefixes_and_x_separator(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "SKU-1001,Licuadora,1 pieza,,20,piezas,2026-11-02\n"
            "SKU-1002,Plancha,1 pieza,,18,piezas,2026-11-02\n"
            "SKU-1003,Extractor,1 pieza,,37,piezas,2026-11-02\n"
        )

        for query, expected_sku in (
            ("Sq 1001", "SKU-1001"),
            ("SKU x 1002", "SKU-1002"),
            ("Scu 1003", "SKU-1003"),
            ("Dime el square 1001", "SKU-1001"),
            ("Ese ka u 1002", "SKU-1002"),
            ("Es que u 1003", "SKU-1003"),
            ("SKU equis 10 01", "SKU-1001"),
            ("Cuánto inventario tenemos del skamil uno", "SKU-1001"),
            ("¿Cuánto inventario tenemos del SK u 1001?", "SKU-1001"),
            ("Dame el inventario de productos, 1001.", "SKU-1001"),
            ("Dame el inventario del SKUP 1002", "SKU-1002"),
            ("O K. Dame el inventario del SK u 1001", "SKU-1001"),
            ("¿Cuánto inventario hay del SQU 1001?", "SKU-1001"),
            ("¿Cuánto inventario hay del SQU-1001?", "SKU-1001"),
            ("¿Cuánto inventario hay del S K U 1001?", "SKU-1001"),
            ("¿Cuánto inventario hay del SQU 1001 enviar este mensaje?", "SKU-1001"),
        ):
            with self.subTest(query=query):
                response = self.query_inventory(query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "found")
                self.assertEqual(response.json()["item"]["sku"], expected_sku)

    def test_spoken_sku_that_does_not_exist_is_not_fuzzily_matched(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "SKU-1001,Licuadora,1 pieza,,20,piezas,2026-11-02\n"
            "SKU-1002,Plancha,1 pieza,,18,piezas,2026-11-02\n"
        )

        response = self.query_inventory("SKU 9999")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "not_found"})

    def test_spoken_sku_preserves_leading_zeroes_and_reports_ambiguous_suffixes(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "SKU-0010,Producto A,1 pieza,,20,piezas,2026-11-02\n"
            "SKU-10,Producto B,1 pieza,,18,piezas,2026-11-02\n"
        )

        response = self.query_inventory("SKU 0010")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ambiguous")
        self.assertEqual(
            {item["sku"] for item in response.json()["candidates"]},
            {"SKU-0010", "SKU-10"},
        )

    def test_does_not_guess_spoken_sku_with_extra_product_words(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "SKU-1001,Licuadora,1 pieza,,20,piezas,2026-11-02\n"
        )

        response = self.query_inventory("Sq 1001 plancha")

        self.assertEqual(response.json(), {"status": "not_found"})

    def test_returns_matches_for_each_requested_product(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "PL-001,Plancha de vapor,1 pieza,plancha; plancha ropa,18,piezas,2026-11-02\n"
            "PL-002,Plancha de cabello,1 pieza,plancha; plancha ropa,6,piezas,2026-11-02\n"
            "EX-001,Extractor de humedad,1 pieza,extractor; extractor de humedad,37,piezas,2026-11-02\n"
            "OL-001,Olla de coccion lenta,1 pieza,olla,14,piezas,2026-11-02\n"
            "LA-001,Lampara de escritorio,1 pieza,lampara,7,piezas,2026-11-02\n"
        )

        response = self.query_inventory(
            "Río dame, los inventarios de planchas, extractor, olla y lámpara por favor"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "multiple_matches")
        matches = {match["term"]: match for match in payload["matches"]}
        self.assertEqual(set(matches), {"plancha", "extractor", "olla", "lampara"})
        self.assertEqual(
            {item["sku"] for item in matches["plancha"]["items"]},
            {"PL-001", "PL-002"},
        )
        self.assertEqual(matches["extractor"]["items"][0]["sku"], "EX-001")
        self.assertEqual(matches["olla"]["items"][0]["sku"], "OL-001")
        self.assertEqual(matches["lampara"]["items"][0]["sku"], "LA-001")

    def test_returns_requested_random_sku_count(self):
        rows = [
            f"SKU-{index:04d},Producto {index},1 pieza,,{index},piezas,2026-11-02"
            for index in range(1, 11)
        ]
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            + "\n".join(rows)
            + "\n"
        )

        response = self.query_inventory("Río dame, una lista de 5 skup al azar")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "random_selection")
        self.assertEqual(len(payload["items"]), 5)
        self.assertEqual(len({item["sku"] for item in payload["items"]}), 5)

    def test_tolerates_unrelated_voice_transcription_words(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "SKU-1001,Licuadora de 3 velocidades ECO,1 pieza,licuadora; licuadora eco,37,piezas,2026-11-02\n"
            "SKU-1002,Plancha de vapor,1 pieza,plancha,44,piezas,2026-11-02\n"
        )

        response = self.query_inventory(
            "Río confírmeme cuánto inventario queda de la licuadora ah o k la canción"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "found")
        self.assertEqual(response.json()["item"]["sku"], "SKU-1001")
        self.assertEqual(response.json()["item"]["available"], "37")

    def test_normalizes_missing_or_spoken_sku_separators(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "SKU-1001,Licuadora,1 pieza,licuadora,37,piezas,2026-11-02\n"
            "SKU-1005,Jabones,12 piezas,jabones,20,paquetes,2026-11-02\n"
        )

        cases = (
            ("¿Cuánta existencia hay del SK 1001?", "SKU-1001"),
            ("¿Cuánta existencia hay del SKU 1001?", "SKU-1001"),
            ("¿Cuánta existencia hay del S K 1 0 0 1?", "SKU-1001"),
            ("¿Qué fecha de actualización tiene el eskiu mil cinco?", "SKU-1005"),
        )
        for query, expected_sku in cases:
            with self.subTest(query=query):
                self.assertIn(expected_sku, normalize_inventory_query(query))
                response = self.query_inventory(query)
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "found")
                self.assertEqual(payload["item"]["sku"], expected_sku)

    def test_returns_and_labels_closest_match_for_voice_word_variant(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "SKU-1001,Licuadora de 3 velocidades ECO,1 pieza,licuadora; licuadora eco,37,piezas,2026-11-02\n"
            "SKU-1002,Plancha de vapor,1 pieza,plancha,44,piezas,2026-11-02\n"
        )

        response = self.query_inventory(
            "Río confirme cuánta inventoria tenemos de licuadores"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "closest_match")
        self.assertEqual(response.json()["item"]["sku"], "SKU-1001")
        self.assertEqual(response.json()["item"]["available"], "37")

    def test_returns_closest_candidates_for_ambiguous_voice_word_variant(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "PL-001,Plancha de vapor,1 pieza,plancha,18,piezas,2026-11-02\n"
            "PL-002,Plancha de cabello,1 pieza,plancha,6,piezas,2026-11-02\n"
        )

        response = self.query_inventory("plancho")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "closest_match")
        self.assertEqual(len(response.json()["candidates"]), 2)

    def test_ambiguous_match_returns_each_stock_separately(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "CL-001,Cloro,1 litro,,18,piezas,2026-11-02\n"
            "CL-004,Cloro,4 litros,,6,piezas,2026-11-02\n"
        )

        response = self.query_inventory("¿Cuánto cloro tenemos?")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ambiguous")
        self.assertEqual(len(response.json()["candidates"]), 2)
        self.assertEqual(
            [candidate["available"] for candidate in response.json()["candidates"]],
            ["18", "6"],
        )

    def test_returns_not_found_without_guessing(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "CL-001,Cloro,1 litro,,18,piezas,2026-11-02\n"
        )

        response = self.query_inventory("¿Cuánto jabón de 1 litro hay?")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "not_found"})

    def test_recognizes_help_questions_without_searching_for_a_product(self):
        response = self.query_inventory("¿En qué puedes ayudarme?")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "help"})

    def test_recognizes_greetings_without_searching_for_a_product(self):
        response = self.query_inventory("¡Hola!")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "greeting"})

    def test_inventory_query_with_help_word_still_searches_for_product(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "CL-001,Cloro,1 litro,,18,piezas,2026-11-02\n"
        )

        response = self.query_inventory("Necesito ayuda, ¿cuánto cloro queda?")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "found")

    def test_empty_template_returns_clear_service_unavailable(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
        )

        response = self.query_inventory("cloro de litro")

        self.assertEqual(response.status_code, 503)
        self.assertIn("todavía no contiene productos", response.json()["detail"])

    def test_invalid_stock_is_rejected(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "CL-001,Cloro,1 litro,,-2,piezas,2026-11-02\n"
        )

        response = self.query_inventory("cloro de litro")

        self.assertEqual(response.status_code, 503)
        self.assertIn("no negativo", response.json()["detail"])

    def test_missing_query_fields_are_rejected(self):
        response = self.client.post(
            "/api/inventory/query",
            json={},
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        self.assertEqual(response.status_code, 422)

    def test_inventory_query_requires_login(self):
        response = self.client.post("/api/inventory/query", json={"query": "cloro"})

        self.assertEqual(response.status_code, 401)

    def test_inventory_catalog_requires_login(self):
        response = self.client.get("/api/inventory/catalog")

        self.assertEqual(response.status_code, 401)

    def test_login_returns_short_lived_bearer_token_without_cache(self):
        response = self.client.post(
            "/api/inventory/login",
            json={"username": "Almacén1", "password": "inventory-test-only-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["token_type"], "bearer")
        self.assertEqual(response.json()["expires_in"], backend_app.INVENTORY_TOKEN_TTL_SECONDS)
        self.assertEqual(response.headers["cache-control"], "no-store, private")
        self.assertEqual(backend_app.verify_inventory_token(response.json()["access_token"]), "Almacén1")

    def test_login_rejects_incorrect_credentials(self):
        response = self.client.post(
            "/api/inventory/login",
            json={"username": "Almacén1", "password": "incorrecta"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"],
            "Usuario o contraseña incorrectos, por favor verifique de nuevo.",
        )

    def test_inventory_login_fails_closed_when_credentials_or_signing_secret_are_missing(self):
        with (
            patch.object(backend_app, "INVENTORY_USERNAME", ""),
            patch.object(backend_app, "INVENTORY_PASSWORD", ""),
            patch.object(backend_app, "INVENTORY_AUTH_SECRET", "short"),
        ):
            login_response = self.client.post(
                "/api/inventory/login",
                json={"username": "demo", "password": "demo"},
            )
            inventory_response = self.client.post(
                "/api/inventory/query",
                json={"query": "cloro"},
            )

        self.assertEqual(login_response.status_code, 503)
        self.assertEqual(inventory_response.status_code, 503)

    def test_inventory_rejects_expired_or_tampered_tokens(self):
        expired_token = backend_app.encode_inventory_token(
            "Almacén1",
            int(backend_app.time.time()) - 1,
        )
        tampered_token = f"{self.access_token[:-1]}x"
        for token in (expired_token, tampered_token):
            response = self.client.get(
                "/api/inventory/catalog",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 401)

    def test_catalog_lists_stock_only_after_authenticated_request(self):
        self.write_inventory(
            "sku,producto,presentacion,aliases,existencia_disponible,unidad,actualizado\n"
            "CL-001,Cloro,1 litro,,18,piezas,2026-11-02\n"
        )
        with patch.object(backend_app, "INVENTORY_CSV_PATH", self.inventory_path):
            response = self.client.get(
                "/api/inventory/catalog",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["sku"], "CL-001")
        self.assertEqual(response.json()["items"][0]["available"], "18")
        self.assertEqual(response.headers["cache-control"], "no-store, private")


if __name__ == "__main__":
    unittest.main()
