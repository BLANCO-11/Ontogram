#!/usr/bin/env python3
"""
ontogram_backend.py - MemoryBackend port + cognee REST adapters

Ontogram's tools, client, and UI depend on this narrow contract — never on
cognee's REST surface directly. Upgrading cognee means adding/adjusting an
adapter here and setting ONTOGRAM_BACKEND_DIALECT; nothing above this file
changes.

Dialects:
  "1.4"    cognee 1.4.0 REST (the long-proven Ontogram base)
  "latest" newer cognee REST (implemented in Phase U; raises NotImplementedError)
  "auto"   probe the daemon once at startup and pick (logged loudly)

All adapter methods are async and return typed results — raw HTTP shapes never
leak above this line.
"""

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass, field
from typing import Optional, Protocol

import httpx


# --------------------------------------------------------------------------- #
# Typed results
# --------------------------------------------------------------------------- #
@dataclass
class DatasetInfo:
    id: str
    name: str


@dataclass
class WriteResult:
    ok: bool
    status_code: int
    dataset: str = ""
    detail: str = ""          # error text or pipeline status payload
    accepted: bool = True     # False when the daemon rejected outright


@dataclass
class RecallHit:
    text: str
    raw: dict = field(default_factory=dict)


@dataclass
class GraphData:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)


class BackendError(RuntimeError):
    """Transport-level failure (unreachable backend, non-JSON, etc.)."""


# --------------------------------------------------------------------------- #
# Port
# --------------------------------------------------------------------------- #
class MemoryBackend(Protocol):
    dialect: str

    async def remember(self, text: str, dataset: str, user_id: str, background: bool = True) -> WriteResult: ...
    async def recall(self, query: str, dataset: str, user_id: str) -> list[RecallHit]: ...
    async def list_datasets(self) -> list[DatasetInfo]: ...
    async def get_graph(self, dataset: str) -> GraphData: ...
    async def delete_dataset(self, dataset: str) -> bool: ...
    async def delete_data_item(self, dataset: str, item_id: str) -> bool: ...
    async def health(self) -> bool: ...


# --------------------------------------------------------------------------- #
# Shared plumbing
# --------------------------------------------------------------------------- #
def _headers(user_id: str, token: str | None) -> dict:
    h = {"X-User-Id": user_id}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


class _BaseRESTAdapter:
    """HTTP plumbing shared by dialect adapters; subclasses set endpoint maps."""

    dialect = "abstract"

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout)

    # -- helpers every dialect shares ----------------------------------------
    async def _dataset_id(self, c: httpx.AsyncClient, dataset: str) -> Optional[str]:
        infos = await self.list_datasets()
        for info in infos:
            if info.name == dataset:
                return info.id
        return None


# --------------------------------------------------------------------------- #
# cognee 1.4.x REST dialect (the proven one)
# --------------------------------------------------------------------------- #
class Cognee14xAdapter(_BaseRESTAdapter):
    """cognee 1.4.0 REST surface (anonymous / single-tenant posture):

        POST   /api/v1/remember            (multipart: data file + form)
        POST   /api/v1/recall              {query, datasets:[names]}
        GET    /api/v1/datasets            -> [{id, name}]
        GET    /api/v1/datasets/{id}/graph -> {nodes, edges}
        DELETE /api/v1/datasets/{id}
        DELETE /api/v1/datasets/{id}/data/{data_id}
        GET    /docs                       (liveness)

    NOTE: without backend access control every caller is the same underlying
    user, so dataset scoping organizes WRITES but graph search can traverse
    across datasets. Hard multi-agent isolation requires the `-acl` dialect.
    """

    dialect = "1.4"

    async def remember(self, text: str, dataset: str, user_id: str, background: bool = True) -> WriteResult:
        files = {"data": ("memory.txt", text.encode("utf-8"), "text/plain")}
        data = {"datasetName": dataset, "run_in_background": "true" if background else "false"}
        try:
            async with self._client() as c:
                r = await c.post(f"{self.base_url}/api/v1/remember",
                                 files=files, data=data, headers=_headers(user_id, self.token))
        except httpx.RequestError as exc:
            raise BackendError(f"backend unreachable at {self.base_url}: {exc}") from exc
        if r.status_code in (200, 201, 202):
            return WriteResult(ok=True, status_code=r.status_code, dataset=dataset, detail=r.text[:500])
        return WriteResult(ok=False, status_code=r.status_code, dataset=dataset,
                           detail=r.text[:500], accepted=False)

    async def recall(self, query: str, dataset: str, user_id: str) -> list[RecallHit]:
        # CRITICAL: the field is `datasets` (a LIST). An earlier version sent
        # `datasetName` (singular) which the router silently ignores — recall
        # then searched ALL datasets, silently breaking scope isolation.
        payload = {"query": query, "datasets": [dataset]}
        try:
            async with self._client() as c:
                r = await c.post(f"{self.base_url}/api/v1/recall",
                                 json=payload,
                                 headers=_headers(user_id, self.token))
        except httpx.RequestError as exc:
            raise BackendError(f"backend unreachable at {self.base_url}: {exc}") from exc
        if r.status_code != 200:
            raise BackendError(f"recall failed: HTTP {r.status_code}: {r.text[:500]}")
        try:
            results = r.json()
        except ValueError as exc:
            raise BackendError(f"non-JSON recall response: {r.text[:500]}") from exc
        hits = []
        for item in results if isinstance(results, list) else []:
            t = (item.get("text") or "").strip() if isinstance(item, dict) else ""
            if t:
                hits.append(RecallHit(text=t, raw=item))
        return hits

    async def list_datasets(self, user_id: Optional[str] = None) -> list[DatasetInfo]:
        try:
            async with self._client() as c:
                r = await c.get(f"{self.base_url}/api/v1/datasets", headers=_headers("", self.token))
        except httpx.RequestError as exc:
            raise BackendError(f"backend unreachable at {self.base_url}: {exc}") from exc
        if r.status_code != 200:
            raise BackendError(f"list datasets failed: HTTP {r.status_code}")
        try:
            rows = r.json()
        except ValueError as exc:
            raise BackendError(f"non-JSON dataset list") from exc
        return [DatasetInfo(id=d["id"], name=d["name"]) for d in rows
                if isinstance(d, dict) and d.get("id") and d.get("name")]

    async def get_graph(self, dataset: str, user_id: Optional[str] = None) -> GraphData:
        async with self._client() as c:
            did = await self._dataset_id(c, dataset)
            if not did:
                return GraphData()
            r = await c.get(f"{self.base_url}/api/v1/datasets/{did}/graph")
        if r.status_code != 200:
            raise BackendError(f"graph fetch failed: HTTP {r.status_code}")
        g = r.json()
        return GraphData(nodes=g.get("nodes", []), edges=g.get("edges", g.get("relationships", [])))

    async def delete_dataset(self, dataset: str, user_id: Optional[str] = None) -> bool:
        async with self._client() as c:
            did = await self._dataset_id(c, dataset)
            if not did:
                return False
            r = await c.delete(f"{self.base_url}/api/v1/datasets/{did}", headers=_headers("", self.token))
        return r.status_code in (200, 202, 204)

    async def delete_data_item(self, dataset: str, item_id: str, user_id: Optional[str] = None) -> bool:
        async with self._client() as c:
            did = await self._dataset_id(c, dataset)
            if not did:
                return False
            r = await c.delete(f"{self.base_url}/api/v1/datasets/{did}/data/{item_id}",
                               headers=_headers("", self.token))
        return r.status_code in (200, 202, 204)

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{self.base_url}/docs")
                return r.status_code == 200
        except httpx.RequestError:
            return False


# --------------------------------------------------------------------------- #
# cognee 1.4.x with backend access control (hard per-identity isolation)
# --------------------------------------------------------------------------- #
class Cognee14xACLAdapter(Cognee14xAdapter):
    """Same REST surface, but under ENABLE_BACKEND_ACCESS_CONTROL=true.

    cognee then runs multi-tenant: each identity gets its own graph/vector
    databases, so scope boundaries are physically enforced. The adapter maps
    Ontogram identities to real cognee users transparently:

      * ``global`` / legacy identities  -> the daemon's default user
        (DEFAULT_USER_EMAIL / DEFAULT_USER_PASSWORD, which also owns all
        pre-ACL memories, keeping them reachable)
      * every other user_id (project slug) -> a provisioned per-project user
        ``<slug>@<domain>`` whose password is derived via HMAC from
        ONTOGRAM_IDP_SECRET (stable across restarts; auto-generated and
        persisted next to cognee's data if unset)

    Tokens are cached per identity and refreshed once on 401.
    """

    dialect = "1.4-acl"

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 300.0,
                 idp_secret: Optional[str] = None, domain: str = "ontogram.dev",
                 default_email: Optional[str] = None, default_password: Optional[str] = None):
        super().__init__(base_url, token, timeout)
        self.domain = domain
        self.default_email = default_email or os.getenv("DEFAULT_USER_EMAIL", "") or "default_user@example.com"
        self.default_password = default_password or os.getenv("DEFAULT_USER_PASSWORD", "") or "default_password"
        self._idp_secret = idp_secret or self._load_or_create_secret()
        self._tokens: dict[str, str] = {}

    @staticmethod
    def _load_or_create_secret() -> str:
        import pathlib
        env = os.getenv("ONTOGRAM_IDP_SECRET", "").strip()
        if env:
            return env
        # persist next to cognee storage so restarts keep credentials stable
        path = pathlib.Path(os.getenv("DATA_ROOT_DIRECTORY", "/root/.cognee/data_storage")).parent / "ontogram_idp_secret"
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
            secret = uuid.uuid4().hex
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secret, encoding="utf-8")
            return secret
        except OSError:
            print("[ontogram_backend] WARNING: ONTOGRAM_IDP_SECRET unset and not persistable; "
                  "provisioned identities will change on restart", flush=True)
            return uuid.uuid4().hex

    def _email(self, user_id: str) -> str:
        if user_id in ("global", "", "default"):
            return self.default_email  # legacy/global identity == default user
        return f"{user_id}@{self.domain}"

    def _password(self, user_id: str) -> str:
        if user_id in ("global", "", "default"):
            return self.default_password  # legacy/global identity == default user
        msg = ("ontogram-identity:" + user_id).encode()
        return hmac.new(self._idp_secret.encode(), msg, hashlib.sha256).hexdigest()

    async def _auth_headers(self, c: httpx.AsyncClient, user_id: str, retry: bool = True) -> dict:
        tok = self._tokens.get(user_id)
        if tok is None:
            email, password = self._email(user_id), self._password(user_id)
            reg = await c.post(f"{self.base_url}/api/v1/auth/register",
                               json={"email": email, "password": password})
            if reg.status_code not in (200, 201) and "already" not in reg.text.lower():
                # 400 with REGISTER_USER_ALREADY_EXISTS-style detail is fine
                if reg.status_code != 400:
                    raise BackendError(f"user provisioning failed: HTTP {reg.status_code}: {reg.text[:200]}")
            login = await c.post(f"{self.base_url}/api/v1/auth/login",
                                 data={"username": email, "password": password})
            if login.status_code != 200:
                raise BackendError(f"identity login failed for '{user_id}': HTTP {login.status_code}")
            tok = login.json().get("access_token")
            self._tokens[user_id] = tok
        h = {"Authorization": f"Bearer {tok}"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"  # explicit token overrides
        return h

    async def _call(self, method: str, url: str, user_id: str, **kw):
        """Authenticated request with one re-login retry on 401."""
        async with self._client() as c:
            headers = await self._auth_headers(c, user_id)
            r = await c.request(method, url, headers=headers, **kw)
            if r.status_code == 401 and retry:
                self._tokens.pop(user_id, None)
                headers = await self._auth_headers(c, user_id, retry=False)
                r = await c.request(method, url, headers=headers, **kw)
        return r

    async def remember(self, text: str, dataset: str, user_id: str, background: bool = True) -> WriteResult:
        files = {"data": ("memory.txt", text.encode("utf-8"), "text/plain")}
        data = {"datasetName": dataset, "run_in_background": "true" if background else "false"}
        try:
            r = await self._call("POST", f"{self.base_url}/api/v1/remember", user_id,
                                 files=files, data=data)
        except httpx.RequestError as exc:
            raise BackendError(f"backend unreachable at {self.base_url}: {exc}") from exc
        if r.status_code in (200, 201, 202):
            return WriteResult(ok=True, status_code=r.status_code, dataset=dataset, detail=r.text[:500])
        return WriteResult(ok=False, status_code=r.status_code, dataset=dataset,
                           detail=r.text[:500], accepted=False)

    async def recall(self, query: str, dataset: str, user_id: str) -> list[RecallHit]:
        try:
            r = await self._call("POST", f"{self.base_url}/api/v1/recall", user_id,
                                 json={"query": query, "datasets": [dataset]})
        except httpx.RequestError as exc:
            raise BackendError(f"backend unreachable at {self.base_url}: {exc}") from exc
        if r.status_code != 200:
            raise BackendError(f"recall failed: HTTP {r.status_code}: {r.text[:500]}")
        try:
            results = r.json()
        except ValueError as exc:
            raise BackendError(f"non-JSON recall response: {r.text[:500]}") from exc
        hits = []
        for item in results if isinstance(results, list) else []:
            t = (item.get("text") or "").strip() if isinstance(item, dict) else ""
            if t:
                hits.append(RecallHit(text=t, raw=item))
        return hits

    async def list_datasets(self, user_id: Optional[str] = None) -> list[DatasetInfo]:
        uid = user_id or "global"
        try:
            r = await self._call("GET", f"{self.base_url}/api/v1/datasets", uid)
        except httpx.RequestError as exc:
            raise BackendError(f"backend unreachable at {self.base_url}: {exc}") from exc
        if r.status_code != 200:
            raise BackendError(f"list datasets failed: HTTP {r.status_code}")
        try:
            rows = r.json()
        except ValueError as exc:
            raise BackendError("non-JSON dataset list") from exc
        return [DatasetInfo(id=d["id"], name=d["name"]) for d in rows
                if isinstance(d, dict) and d.get("id") and d.get("name")]

    async def get_graph(self, dataset: str, user_id: str = "global") -> GraphData:
        infos = {i.name: i.id for i in await self.list_datasets(user_id)}
        did = infos.get(dataset)
        if not did:
            return GraphData()
        r = await self._call("GET", f"{self.base_url}/api/v1/datasets/{did}/graph", user_id)
        if r.status_code != 200:
            raise BackendError(f"graph fetch failed: HTTP {r.status_code}")
        g = r.json()
        return GraphData(nodes=g.get("nodes", []), edges=g.get("edges", g.get("relationships", [])))

    async def delete_dataset(self, dataset: str, user_id: str = "global") -> bool:
        infos = {i.name: i.id for i in await self.list_datasets(user_id)}
        did = infos.get(dataset)
        if not did:
            return False
        r = await self._call("DELETE", f"{self.base_url}/api/v1/datasets/{did}", user_id)
        return r.status_code in (200, 202, 204)

    async def delete_data_item(self, dataset: str, item_id: str, user_id: str = "global") -> bool:
        infos = {i.name: i.id for i in await self.list_datasets(user_id)}
        did = infos.get(dataset)
        if not did:
            return False
        r = await self._call("DELETE", f"{self.base_url}/api/v1/datasets/{did}/data/{item_id}", user_id)
        return r.status_code in (200, 202, 204)


# --------------------------------------------------------------------------- #
# Placeholder for the upgrade spike (Phase U)
# --------------------------------------------------------------------------- #
class CogneeLatestAdapter(Cognee14xACLAdapter):
    """Reserved for the Phase U spike against a current cognee core.

    Implemented incrementally: override only the methods whose routes/shapes
    changed upstream; everything else inherits.
    """

    dialect = "latest"


# --------------------------------------------------------------------------- #
# Factory + capability probe
# --------------------------------------------------------------------------- #
_DIALECTS = {"1.4": Cognee14xAdapter, "1.4-acl": Cognee14xACLAdapter, "latest": CogneeLatestAdapter}


async def detect_dialect(base_url: str) -> str:
    """Probe the daemon and guess its REST dialect.

    Unauthenticated GET /api/v1/datasets:
      200 + JSON list  -> "1.4"   (access control off; single shared identity)
      401              -> "1.4-acl" (multi-tenant posture; per-identity auth)
      unreachable      -> BackendError so misconfigurations fail loudly
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{base_url.rstrip('/')}/api/v1/datasets")
    except httpx.RequestError as exc:
        raise BackendError(f"cannot reach backend at {base_url}: {exc}") from exc
    if r.status_code == 200:
        try:
            r.json()
            return "1.4"
        except ValueError:
            pass
    if r.status_code == 401:
        return "1.4-acl"
    raise BackendError(f"unexpected probe response: HTTP {r.status_code}")


async def create_backend(base_url: Optional[str] = None,
                         dialect: str = "auto",
                         token: Optional[str] = None) -> MemoryBackend:
    base_url = (base_url or os.getenv("COGNEE_API_URL", "http://localhost:9480")).rstrip("/")
    token = token if token is not None else (os.getenv("ONTOGRAM_TOKEN", "").strip() or None)
    if dialect == "auto":
        dialect = os.getenv("ONTOGRAM_BACKEND_DIALECT", "").strip() or await detect_dialect(base_url)
    cls = _DIALECTS.get(dialect)
    if cls is None:
        raise BackendError(f"unknown ONTOGRAM_BACKEND_DIALECT '{dialect}' (expected one of {sorted(_DIALECTS)})")
    return cls(base_url=base_url, token=token)
