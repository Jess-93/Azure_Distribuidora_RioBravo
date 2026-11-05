import base64
import hashlib
import hmac
import json
import logging
import ipaddress
import os
import re
import socket
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from azure.ai.projects import AIProjectClient
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import CredentialUnavailableError, DefaultAzureCredential
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.inventory import (
    InventoryFileError,
    list_inventory,
    normalize_inventory_query,
    search_inventory,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env.local")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("rio-claro-backend")

PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
AGENT_NAME = os.getenv("FOUNDRY_AGENT_NAME", "").strip()
INVENTORY_AGENT_ENDPOINT = os.getenv("FOUNDRY_INVENTORY_AGENT_ENDPOINT", "").strip()
SESSION_DB_PATH = Path(
    os.getenv("CHAT_SESSION_DB_PATH", str(ROOT_DIR / ".data" / "chat_sessions.sqlite3"))
).expanduser()
MAX_REQUESTS_PER_MINUTE = int(os.getenv("CHAT_REQUESTS_PER_MINUTE", "60"))
SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "").strip()
SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "").strip()
SPEECH_REQUESTS_PER_MINUTE = int(os.getenv("SPEECH_REQUESTS_PER_MINUTE", "30"))
SPEECH_GLOBAL_REQUESTS_PER_MINUTE = int(os.getenv("SPEECH_GLOBAL_REQUESTS_PER_MINUTE", "300"))
SPEECH_TRUSTED_PROXY_CIDRS = tuple(
    ipaddress.ip_network(cidr.strip(), strict=False)
    for cidr in os.getenv("SPEECH_TRUSTED_PROXY_CIDRS", "").split(",")
    if cidr.strip()
)
SPEECH_TOKEN_TIMEOUT_SECONDS = 5
MAX_MESSAGE_LENGTH = 4000
MAX_REQUEST_SIZE = 16 * 1024
INVENTORY_CSV_PATH = ROOT_DIR / "backend" / "data" / "inventario.csv"
INVENTORY_USERNAME = os.getenv("ALMACEN_USERNAME", "").strip()
INVENTORY_PASSWORD = os.getenv("ALMACEN_PASSWORD", "")
INVENTORY_AUTH_SECRET = os.getenv("INVENTORY_AUTH_SECRET", "")
INVENTORY_TOKEN_TTL_SECONDS = 60 * 60
INVENTORY_LOGIN_REQUESTS_PER_MINUTE = 5
INVENTORY_LOGIN_GLOBAL_REQUESTS_PER_MINUTE = 30

if MAX_REQUESTS_PER_MINUTE < 1:
    raise ValueError("CHAT_REQUESTS_PER_MINUTE debe ser un entero positivo.")
if SPEECH_REQUESTS_PER_MINUTE < 1 or SPEECH_GLOBAL_REQUESTS_PER_MINUTE < 1:
    raise ValueError("Los límites SPEECH_REQUESTS_PER_MINUTE y SPEECH_GLOBAL_REQUESTS_PER_MINUTE deben ser positivos.")

app = FastAPI(title="Distribuidora Río Claro Chat API", docs_url=None, redoc_url=None)
foundry_lock = threading.Lock()
session_lock = threading.Lock()
rate_limit_lock = threading.Lock()
speech_rate_limit_lock = threading.Lock()
request_times = deque()
speech_request_times_by_client = OrderedDict()
speech_global_request_times = deque()
inventory_login_request_times_by_client = OrderedDict()
inventory_login_global_request_times = deque()
foundry_project = None
foundry_openai_client = None
inventory_openai_client = None


@contextmanager
def session_database():
    connection = sqlite3.connect(SESSION_DB_PATH, timeout=30)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class ChatContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch: Annotated[str, Field(min_length=1, max_length=80)] = "Guadalajara"
    role: Annotated[str, Field(min_length=1, max_length=40)] = "Cliente"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)]
    sessionId: Annotated[str, Field(min_length=36, max_length=36)]
    context: ChatContext = Field(default_factory=ChatContext)


class InventoryQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1, max_length=250)]


class InventoryChatRequest(InventoryQueryRequest):
    sessionId: Annotated[str, Field(min_length=36, max_length=36)]


class InventoryLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Annotated[str, Field(min_length=1, max_length=80)]
    password: Annotated[str, Field(min_length=1, max_length=200)]


def initialize_session_store():
    SESSION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with session_database() as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chat_sessions'"
        ).fetchone()
        if table_exists:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(chat_sessions)").fetchall()
            }
            if "foundry_session_id" in columns:
                connection.execute("DROP TABLE chat_sessions")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                client_session_id TEXT PRIMARY KEY,
                previous_response_id TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_chat_sessions (
                client_session_id TEXT NOT NULL,
                agent_endpoint TEXT NOT NULL,
                previous_response_id TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (client_session_id, agent_endpoint)
            )
            """
        )


initialize_session_store()


def enforce_rate_limit():
    now = time.monotonic()
    with rate_limit_lock:
        while request_times and request_times[0] <= now - 60:
            request_times.popleft()
        if len(request_times) >= MAX_REQUESTS_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Se alcanzó el límite temporal de mensajes. Intenta más tarde.")
        request_times.append(now)


def get_foundry_clients():
    global foundry_project, foundry_openai_client

    if not PROJECT_ENDPOINT or not AGENT_NAME:
        raise RuntimeError(
            "El backend debe configurar FOUNDRY_PROJECT_ENDPOINT y FOUNDRY_AGENT_NAME."
        )

    with foundry_lock:
        if foundry_project is None:
            credential = DefaultAzureCredential()
            foundry_project = AIProjectClient(
                endpoint=PROJECT_ENDPOINT,
                credential=credential,
                allow_preview=True,
            )
        if foundry_openai_client is None:
            foundry_openai_client = foundry_project.get_openai_client(agent_name=AGENT_NAME)

    return foundry_project, foundry_openai_client


def normalized_inventory_agent_endpoint():
    if not INVENTORY_AGENT_ENDPOINT:
        return ""
    parsed_endpoint = urlsplit(INVENTORY_AGENT_ENDPOINT)
    if (
        parsed_endpoint.scheme != "https"
        or not parsed_endpoint.netloc
        or parsed_endpoint.username
        or parsed_endpoint.password
        or parsed_endpoint.query
        or parsed_endpoint.fragment
    ):
        raise RuntimeError("FOUNDRY_INVENTORY_AGENT_ENDPOINT debe ser una URL HTTPS válida.")

    path = parsed_endpoint.path.rstrip("/")
    if path.endswith("/endpoint"):
        path += "/protocols/openai"
    elif not path.endswith("/endpoint/protocols/openai"):
        raise RuntimeError(
            "FOUNDRY_INVENTORY_AGENT_ENDPOINT debe apuntar al endpoint OpenAI del agente "
            "o terminar en /endpoint."
        )
    if not PROJECT_ENDPOINT:
        raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT debe configurarse para conectar Foundry.")
    parsed_project_endpoint = urlsplit(PROJECT_ENDPOINT)
    project_path = parsed_project_endpoint.path.rstrip("/")
    if (
        parsed_project_endpoint.scheme != "https"
        or parsed_endpoint.netloc.casefold() != parsed_project_endpoint.netloc.casefold()
        or not path.startswith(f"{project_path}/agents/")
    ):
        raise RuntimeError(
            "El endpoint del agente de almacén debe pertenecer al mismo proyecto de Foundry "
            "configurado en FOUNDRY_PROJECT_ENDPOINT."
        )
    return parsed_endpoint._replace(path=path).geturl()


def get_inventory_foundry_client():
    global foundry_project, inventory_openai_client

    agent_endpoint = normalized_inventory_agent_endpoint()
    if not agent_endpoint:
        return None

    with foundry_lock:
        if foundry_project is None:
            credential = DefaultAzureCredential()
            foundry_project = AIProjectClient(
                endpoint=PROJECT_ENDPOINT,
                credential=credential,
                allow_preview=True,
            )
        if inventory_openai_client is None:
            agent_path = urlsplit(agent_endpoint).path
            agent_name = agent_path.split("/agents/", 1)[1].split("/", 1)[0]
            inventory_openai_client = foundry_project.get_openai_client(agent_name=agent_name)

    return inventory_openai_client


def get_previous_response_id(client_session_id: str):
    with session_lock, session_database() as connection:
        record = connection.execute(
            "SELECT previous_response_id FROM chat_sessions WHERE client_session_id = ?",
            (client_session_id,),
        ).fetchone()
        return record[0] if record else None


def get_previous_inventory_response_id(client_session_id: str, agent_endpoint: str):
    with session_lock, session_database() as connection:
        record = connection.execute(
            """
            SELECT previous_response_id
            FROM inventory_chat_sessions
            WHERE client_session_id = ? AND agent_endpoint = ?
            """,
            (client_session_id, agent_endpoint),
        ).fetchone()
        return record[0] if record else None


def save_previous_inventory_response_id(
    client_session_id: str,
    agent_endpoint: str,
    response_id: str,
):
    with session_lock, session_database() as connection:
        connection.execute(
            """
            INSERT INTO inventory_chat_sessions (
                client_session_id, agent_endpoint, previous_response_id, updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(client_session_id, agent_endpoint) DO UPDATE SET
                previous_response_id = excluded.previous_response_id,
                updated_at = excluded.updated_at
            """,
            (client_session_id, agent_endpoint, response_id, int(time.time())),
        )


def save_previous_response_id(client_session_id: str, response_id: str):
    with session_lock, session_database() as connection:
        connection.execute(
            """
            INSERT INTO chat_sessions (client_session_id, previous_response_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(client_session_id) DO UPDATE SET
                previous_response_id = excluded.previous_response_id,
                updated_at = excluded.updated_at
            """,
            (client_session_id, response_id, int(time.time())),
        )


def extract_sources(result):
    sources = []
    seen_titles = set()
    output = getattr(result, "output", [])

    for item in output if isinstance(output, list) else []:
        item_data = item.model_dump() if hasattr(item, "model_dump") else item
        if not isinstance(item_data, dict) or not isinstance(item_data.get("content"), list):
            continue

        for content in item_data["content"]:
            if not isinstance(content, dict) or not isinstance(content.get("annotations"), list):
                continue
            for annotation in content["annotations"]:
                if not isinstance(annotation, dict) or annotation.get("type") != "file_citation":
                    continue
                title = annotation.get("filename")
                if not isinstance(title, str) or not title.strip() or title in seen_titles:
                    continue

                source = {"title": title.strip()[:120], "section": "Documento consultado"}
                page = annotation.get("page_number")
                if isinstance(page, int) and not isinstance(page, bool) and page > 0:
                    source["page"] = page
                sources.append(source)
                seen_titles.add(title)
                if len(sources) == 5:
                    return sources

    return sources


def clean_foundry_citations(answer: str) -> str:
    cleaned_answer = re.sub(r"\ue200filecite\ue202.*?(?:\ue201|$)", "", answer, flags=re.DOTALL)
    cleaned_answer = re.sub(
        r"\s*,?\s*(?:【(?:\d+:[^】]*|\d+†[^】]*)】|\[\d+:[^\]]*\])",
        "",
        cleaned_answer,
    )
    return cleaned_answer.strip().rstrip(" ,").strip()


@app.middleware("http")
async def protect_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_REQUEST_SIZE:
        return JSONResponse(
            status_code=413,
            content={"detail": "La solicitud excede el tamaño permitido."},
        )
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self' https://*.stt.speech.microsoft.com "
        "wss://*.stt.speech.microsoft.com; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path == "/api/speech/token":
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def enforce_speech_rate_limit(client_ip: str):
    now = time.monotonic()
    with speech_rate_limit_lock:
        while speech_global_request_times and speech_global_request_times[0] <= now - 60:
            speech_global_request_times.popleft()
        client_times = speech_request_times_by_client.get(client_ip)
        if client_times is None:
            client_times = deque()
            speech_request_times_by_client[client_ip] = client_times
        else:
            speech_request_times_by_client.move_to_end(client_ip)
        while client_times and client_times[0] <= now - 60:
            client_times.popleft()

        if (
            len(client_times) >= SPEECH_REQUESTS_PER_MINUTE
            or len(speech_global_request_times) >= SPEECH_GLOBAL_REQUESTS_PER_MINUTE
        ):
            raise HTTPException(
                status_code=429,
                detail="Se alcanzó el límite temporal de solicitudes de dictado. Intenta más tarde.",
            )

        client_times.append(now)
        speech_global_request_times.append(now)
        while len(speech_request_times_by_client) > 2048:
            speech_request_times_by_client.popitem(last=False)


def enforce_inventory_login_rate_limit(client_ip: str):
    now = time.monotonic()
    with speech_rate_limit_lock:
        while inventory_login_global_request_times and inventory_login_global_request_times[0] <= now - 60:
            inventory_login_global_request_times.popleft()
        client_times = inventory_login_request_times_by_client.get(client_ip)
        if client_times is None:
            client_times = deque()
            inventory_login_request_times_by_client[client_ip] = client_times
        else:
            inventory_login_request_times_by_client.move_to_end(client_ip)
        while client_times and client_times[0] <= now - 60:
            client_times.popleft()

        if (
            len(client_times) >= INVENTORY_LOGIN_REQUESTS_PER_MINUTE
            or len(inventory_login_global_request_times) >= INVENTORY_LOGIN_GLOBAL_REQUESTS_PER_MINUTE
        ):
            raise HTTPException(
                status_code=429,
                detail="Se alcanzó el límite temporal de intentos de inicio de sesión. Intenta más tarde.",
            )

        client_times.append(now)
        inventory_login_global_request_times.append(now)
        while len(inventory_login_request_times_by_client) > 2048:
            inventory_login_request_times_by_client.popitem(last=False)


def inventory_auth_is_configured() -> bool:
    return bool(
        INVENTORY_USERNAME
        and INVENTORY_PASSWORD
        and len(INVENTORY_AUTH_SECRET.encode("utf-8")) >= 32
    )


def encode_inventory_token(username: str, expires_at: int) -> str:
    payload = json.dumps(
        {"sub": username, "exp": expires_at},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded_payload = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        INVENTORY_AUTH_SECRET.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{encoded_payload}.{encoded_signature}"


def verify_inventory_token(token: str) -> str | None:
    if not inventory_auth_is_configured():
        return None
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        supplied_signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        expected_signature = hmac.new(
            INVENTORY_AUTH_SECRET.encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None

        payload_bytes = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
        payload = json.loads(payload_bytes)
        username = payload.get("sub")
        expires_at = payload.get("exp")
        if (
            username != INVENTORY_USERNAME
            or not isinstance(expires_at, int)
            or expires_at <= int(time.time())
        ):
            return None
        return username
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def require_inventory_auth(request: Request) -> str:
    if not inventory_auth_is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "El inicio de sesión del almacén no está configurado. "
                "Configura ALMACEN_USERNAME, ALMACEN_PASSWORD e INVENTORY_AUTH_SECRET en el backend."
            ),
        )

    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Inicia sesión para consultar el inventario.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = verify_inventory_token(token.strip())
    if not username:
        raise HTTPException(
            status_code=401,
            detail="La sesión del almacén venció o no es válida. Inicia sesión de nuevo.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


def get_speech_client_ip(request: Request) -> str:
    """Use forwarded client IP only when the direct peer is explicitly trusted."""
    peer = request.client.host if request.client else ""
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer or "unknown"

    if not SPEECH_TRUSTED_PROXY_CIDRS or not any(
        peer_ip in network for network in SPEECH_TRUSTED_PROXY_CIDRS
    ):
        return str(peer_ip)

    forwarded_for = request.headers.get("x-forwarded-for", "")
    if not forwarded_for:
        return str(peer_ip)
    try:
        forwarded_ips = [ipaddress.ip_address(value.strip()) for value in forwarded_for.split(",")]
    except ValueError:
        # A malformed proxy header must never be treated as an asserted client identity.
        return str(peer_ip)

    # Walk from the nearest proxy toward the client; ignore only configured trusted hops.
    for forwarded_ip in reversed(forwarded_ips):
        if not any(forwarded_ip in network for network in SPEECH_TRUSTED_PROXY_CIDRS):
            return str(forwarded_ip)
    return str(forwarded_ips[0])


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/inventory/query")
def inventory_query(payload: InventoryQueryRequest, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store, private"
    require_inventory_auth(request)
    try:
        return search_inventory(payload.query.strip(), INVENTORY_CSV_PATH)
    except ValueError as error:
        status_code = 503 if isinstance(error, InventoryFileError) else 422
        if status_code == 503:
            logger.warning("No se pudo consultar el CSV de inventario: %s", error)
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@app.post("/api/inventory/chat")
def inventory_chat(payload: InventoryChatRequest, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store, private"
    require_inventory_auth(request)
    try:
        client_session_id = str(UUID(payload.sessionId))
    except ValueError as error:
        raise HTTPException(status_code=422, detail="El identificador de sesión no es válido.") from error

    normalized_query = normalize_inventory_query(payload.query.strip())
    try:
        inventory_result = search_inventory(normalized_query, INVENTORY_CSV_PATH)
    except ValueError as error:
        status_code = 503 if isinstance(error, InventoryFileError) else 422
        if status_code == 503:
            logger.warning("No se pudo consultar el CSV de inventario para el chat: %s", error)
        raise HTTPException(status_code=status_code, detail=str(error)) from error

    try:
        openai_client = get_inventory_foundry_client()
        if openai_client is None:
            return {
                "mode": "inventory",
                "assistantResponse": None,
                "result": inventory_result,
            }

        agent_endpoint = normalized_inventory_agent_endpoint()
        previous_response_id = get_previous_inventory_response_id(
            client_session_id,
            agent_endpoint,
        )
        prompt = (
            "Eres Río, el asistente de almacén. Responde en español, con tono cordial y claro. "
            "Interpreta las preguntas de seguimiento usando la conversación previa. Usa exclusivamente "
            "datos verificables del inventario de los resultados actuales o previos; no inventes productos, "
            "existencias, precios, SKU ni fechas. Trata existencias y precios de turnos anteriores como "
            "desactualizados: usa el resultado actual para afirmarlos. Si no hay datos actuales para "
            "contestar, pide una aclaración cordial. Si el resultado indica que no hubo coincidencias, pide "
            "el nombre, la presentación o el SKU; si es una consulta general, explica brevemente qué consultas "
            "puedes atender. Mantén la respuesta concisa y no repitas toda una lista que ya se muestra en la "
            "interfaz.\n\n"
            f"Consulta del colaborador: {normalized_query}\n\n"
            "Resultado actual de la búsqueda autorizada en el inventario (JSON):\n"
            f"{json.dumps(inventory_result, ensure_ascii=False)}"
        )
        response_options = {"input": prompt}
        if previous_response_id:
            response_options["previous_response_id"] = previous_response_id
        result = openai_client.responses.create(**response_options)
        answer = getattr(result, "output_text", None)
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Foundry devolvió una respuesta de almacén sin texto.")
        response_id = getattr(result, "id", None)
        if not isinstance(response_id, str) or not response_id:
            raise RuntimeError(
                "Foundry no devolvió el identificador de respuesta necesario para continuar el chat de almacén."
            )
        save_previous_inventory_response_id(client_session_id, agent_endpoint, response_id)
    except (ClientAuthenticationError, CredentialUnavailableError) as error:
        logger.exception("No se pudieron obtener credenciales para el agente de almacén de Foundry.")
        raise HTTPException(
            status_code=503,
            detail=(
                "El backend no pudo autenticarse con Azure para consultar el agente de almacén. "
                "Revisa Azure CLI o la identidad administrada y sus permisos."
            ),
        ) from error
    except Exception as error:
        logger.exception("No se pudo completar la solicitud al agente de almacén de Foundry.")
        raise HTTPException(
            status_code=502,
            detail="No fue posible obtener una respuesta del agente de almacén. Revisa su endpoint y permisos.",
        ) from error

    logger.info("El agente de Foundry respondió correctamente a una consulta de almacén.")
    return {
        "mode": "agent",
        "assistantResponse": answer.strip(),
        "result": inventory_result,
    }


@app.post("/api/inventory/login")
def inventory_login(payload: InventoryLoginRequest, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store, private"
    if not inventory_auth_is_configured():
        raise HTTPException(
            status_code=503,
            detail="El inicio de sesión del almacén no está configurado en el backend.",
        )

    enforce_inventory_login_rate_limit(get_speech_client_ip(request))
    username_matches = hmac.compare_digest(
        payload.username.strip().encode("utf-8"),
        INVENTORY_USERNAME.encode("utf-8"),
    )
    password_matches = hmac.compare_digest(
        payload.password.encode("utf-8"),
        INVENTORY_PASSWORD.encode("utf-8"),
    )
    if not username_matches or not password_matches:
        raise HTTPException(
            status_code=401,
            detail="Usuario o contraseña incorrectos, por favor verifique de nuevo.",
        )

    expires_at = int(time.time()) + INVENTORY_TOKEN_TTL_SECONDS
    return {
        "access_token": encode_inventory_token(INVENTORY_USERNAME, expires_at),
        "token_type": "bearer",
        "expires_in": INVENTORY_TOKEN_TTL_SECONDS,
    }


@app.get("/api/inventory/catalog")
def inventory_catalog(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store, private"
    require_inventory_auth(request)
    try:
        return {"items": list_inventory(INVENTORY_CSV_PATH)}
    except InventoryFileError as error:
        logger.warning("No se pudo cargar el catálogo de inventario: %s", error)
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/speech/token")
def speech_token(request: Request):
    enforce_speech_rate_limit(get_speech_client_ip(request))

    if not SPEECH_KEY or not SPEECH_REGION:
        raise HTTPException(
            status_code=503,
            detail="El backend debe configurar AZURE_SPEECH_KEY y AZURE_SPEECH_REGION.",
        )
    if "\r" in SPEECH_KEY or "\n" in SPEECH_KEY:
        raise HTTPException(status_code=503, detail="AZURE_SPEECH_KEY tiene un formato no válido.")
    if not re.fullmatch(r"[a-z0-9-]+", SPEECH_REGION, flags=re.IGNORECASE):
        raise HTTPException(status_code=503, detail="AZURE_SPEECH_REGION no tiene un formato válido.")

    upstream_request = URLRequest(
        f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken",
        data=b"",
        headers={"Ocp-Apim-Subscription-Key": SPEECH_KEY, "Content-Length": "0"},
        method="POST",
    )
    try:
        with urlopen(upstream_request, timeout=SPEECH_TOKEN_TIMEOUT_SECONDS) as upstream_response:
            token_bytes = upstream_response.read(8193)
        if len(token_bytes) > 8192:
            raise ValueError("Token de Speech excede el tamaño permitido.")
        token = token_bytes.decode("utf-8").strip()
        if not token or any(character.isspace() or ord(character) < 32 for character in token):
            raise ValueError("Speech no devolvió un token válido.")
    except HTTPError as error:
        logger.warning("El endpoint de emisión de tokens de Azure Speech respondió con HTTP %s.", error.code)
        raise HTTPException(
            status_code=502,
            detail="Azure Speech rechazó la solicitud de token. Revisa la clave y la región configuradas.",
        ) from error
    except (TimeoutError, socket.timeout) as error:
        raise HTTPException(
            status_code=504,
            detail="Azure Speech tardó demasiado en emitir el token.",
        ) from error
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise HTTPException(
                status_code=504,
                detail="Azure Speech tardó demasiado en emitir el token.",
            ) from error
        raise HTTPException(
            status_code=502,
            detail="No fue posible conectar con Azure Speech para emitir el token.",
        ) from error
    except (UnicodeDecodeError, ValueError) as error:
        logger.warning("Azure Speech devolvió una respuesta de token no válida.")
        raise HTTPException(
            status_code=502,
            detail="Azure Speech devolvió una respuesta no válida.",
        ) from error
    except OSError as error:
        raise HTTPException(
            status_code=502,
            detail="No fue posible conectar con Azure Speech para emitir el token.",
        ) from error

    return {"token": token, "region": SPEECH_REGION}


@app.post("/api/chat")
def chat(request: ChatRequest):
    enforce_rate_limit()

    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Escribe una consulta antes de enviar el mensaje.")

    try:
        client_session_id = str(UUID(request.sessionId))
    except ValueError as error:
        raise HTTPException(status_code=422, detail="El identificador de sesión no es válido.") from error

    try:
        _, openai_client = get_foundry_clients()
        previous_response_id = get_previous_response_id(client_session_id)
        prompt = (
            f"Sucursal: {request.context.branch}\n"
            f"Perfil: {request.context.role}\n\n"
            f"Consulta: {message}"
        )
        response_options = {"input": prompt}
        if previous_response_id:
            response_options["previous_response_id"] = previous_response_id
        result = openai_client.responses.create(**response_options)
        answer = getattr(result, "output_text", None)
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Foundry devolvió una respuesta sin texto.")
        response_id = getattr(result, "id", None)
        if not isinstance(response_id, str) or not response_id:
            raise RuntimeError("Foundry no devolvió el identificador de respuesta necesario para continuar el chat.")
        save_previous_response_id(client_session_id, response_id)
    except HTTPException:
        raise
    except (ClientAuthenticationError, CredentialUnavailableError) as error:
        logger.exception("No se pudieron obtener credenciales para Foundry.")
        raise HTTPException(
            status_code=503,
            detail=(
                "El backend no pudo autenticarse con Azure. En local, instala Azure CLI, ejecuta `az login` "
                "y reinicia el backend. En App Service, habilita la identidad administrada y asígnale "
                "permisos para invocar el agente."
            ),
        ) from error
    except Exception as error:
        logger.exception("No se pudo completar la solicitud al agente de Foundry.")
        raise HTTPException(
            status_code=502,
            detail="No fue posible obtener una respuesta de Foundry. Revisa la configuración y los permisos del backend.",
        ) from error

    cleaned_answer = clean_foundry_citations(answer)
    if not cleaned_answer:
        raise HTTPException(
            status_code=502,
            detail="Foundry no devolvió una respuesta legible. Intenta nuevamente.",
        )

    logger.info("Foundry respondió correctamente a una consulta.")
    return {
        "response": cleaned_answer,
        "sources": extract_sources(result),
        "escalateToHuman": False,
    }


DIST_DIR = ROOT_DIR / "dist"
ASSETS_DIR = DIST_DIR / "assets"
if ASSETS_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/{path:path}")
def serve_frontend(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="No existe esta ruta de API.")

    if not DIST_DIR.is_dir():
        raise HTTPException(
            status_code=503,
            detail="No se encontró el frontend compilado. Ejecuta npm run build antes de iniciar el servidor.",
        )

    requested_file = (DIST_DIR / path).resolve()
    if requested_file.is_relative_to(DIST_DIR.resolve()) and requested_file.is_file():
        return FileResponse(requested_file)

    index_file = DIST_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=503, detail="No se encontró dist/index.html.")
    return FileResponse(index_file)
