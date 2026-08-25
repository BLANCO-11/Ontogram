#!/usr/bin/env python3
"""Offline tests for ontogram_backend (no daemon needed) + optional live smoke.

Run:  python3 tests/test_backend.py          # offline suite
      LIVE=1 python3 tests/test_backend.py  # also smoke-test a running daemon

Uses unittest + httpx.MockTransport to verify parsing, error paths, and the
dialect probe without any server.
"""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from ontogram_backend import (
    BackendError,
    Cognee14xAdapter,
    GraphData,
    RecallHit,
    WriteResult,
    create_backend,
    detect_dialect,
)


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


def make_adapter(handler):
    a = Cognee14xAdapter(base_url="http://mock")
    a._client = lambda: mock_client(handler)
    return a


class TestRemember(unittest.TestCase):
    def test_remember_ok(self):
        async def run():
            def handler(request):
                assert request.url.path == "/api/v1/remember"
                return httpx.Response(202, json={"status": "running"})
            a = make_adapter(handler)
            r = await a.remember("fact", "deck_x_memory", "x")
            self.assertIsInstance(r, WriteResult)
            self.assertTrue(r.ok)
            self.assertEqual(r.status_code, 202)
        asyncio.run(run())

    def test_rejects_error_status(self):
        async def run():
            def handler(request):
                return httpx.Response(409, text="conflict")
            a = make_adapter(handler)
            r = await a.remember("fact", "deck_x_memory", "x")
            self.assertFalse(r.ok)
            self.assertFalse(r.accepted)
        asyncio.run(run())


class TestRecall(unittest.TestCase):
    def test_parses_hits(self):
        async def run():
            def handler(request):
                body = json.loads(request.content)
                assert body["datasets"] == ["deck_x_memory"], body  # scoped recall contract
                return httpx.Response(200, json=[{"text": "alpha"}, {"text": ""}, {"other": 1}, "junk"])
            a = make_adapter(handler)
            hits = await a.recall("q", "deck_x_memory", "x")
            self.assertEqual([h.text for h in hits], ["alpha"])
            self.assertIsInstance(hits[0], RecallHit)
        asyncio.run(run())

    def test_error_raises(self):
        async def run():
            def handler(request):
                return httpx.Response(500, text="boom")
            a = make_adapter(handler)
            with self.assertRaises(BackendError):
                await a.recall("q", "deck_x_memory", "x")
        asyncio.run(run())


class TestDatasets(unittest.TestCase):
    def test_list_and_graph_resolution(self):
        async def run():
            def handler(request):
                if request.url.path == "/api/v1/datasets":
                    return httpx.Response(200, json=[{"id": "d1", "name": "deck_a_memory"}])
                if request.url.path == "/api/v1/datasets/d1/graph":
                    return httpx.Response(200, json={"nodes": [{"id": "n1"}], "relationships": [{"s": 1}]})
                return httpx.Response(404)
            a = make_adapter(handler)
            infos = await a.list_datasets()
            self.assertEqual(infos[0].name, "deck_a_memory")
            g = await a.get_graph("deck_a_memory")
            self.assertIsInstance(g, GraphData)
            self.assertEqual(g.nodes[0]["id"], "n1")
            self.assertEqual(g.edges, [{"s": 1}])
        asyncio.run(run())

    def test_graph_missing_dataset_is_empty(self):
        async def run():
            def handler(request):
                return httpx.Response(200, json=[])
            a = make_adapter(handler)
            g = await a.get_graph("nope")
            self.assertEqual(g.nodes, [])
        asyncio.run(run())

    def test_delete_dataset_found_and_missing(self):
        async def run():
            calls = []
            def handler(request):
                calls.append(request.method + request.url.path)
                if request.url.path == "/api/v1/datasets":
                    return httpx.Response(200, json=[{"id": "d9", "name": "deck_b_memory"}])
                if request.method == "DELETE" and request.url.path.startswith("/api/v1/datasets/d9"):
                    return httpx.Response(204)
                return httpx.Response(200, json=[])
            a = make_adapter(handler)
            self.assertTrue(await a.delete_dataset("deck_b_memory"))
            self.assertFalse(await a.delete_dataset("missing"))
            self.assertIn("DELETE/api/v1/datasets/d9", calls)
        asyncio.run(run())


class TestDialectProbe(unittest.TestCase):
    def test_detects_14(self):
        async def run():
            def handler(request):
                return httpx.Response(200, json=[])
            async with mock_client(handler) as c:
                # patch detect to use our transport
                import ontogram_backend as ob
                orig = httpx.AsyncClient
                class FakeClient(orig):
                    def __init__(self, *a, **k):
                        k.pop("transport", None)
                        super().__init__(transport=httpx.MockTransport(handler), timeout=10.0)
                ob.httpx.AsyncClient = FakeClient
                try:
                    self.assertEqual(await detect_dialect("http://mock"), "1.4")
                finally:
                    ob.httpx.AsyncClient = orig
        asyncio.run(run())

    def test_401_means_acl(self):
        async def run():
            import ontogram_backend as ob
            def handler(request):
                return httpx.Response(401, json={"detail": "Unauthorized"})
            orig = httpx.AsyncClient
            class FakeClient(orig):
                def __init__(self, *a, **k):
                    super().__init__(transport=httpx.MockTransport(handler), timeout=10.0)
            ob.httpx.AsyncClient = FakeClient
            try:
                self.assertEqual(await detect_dialect("http://mock"), "1.4-acl")
            finally:
                ob.httpx.AsyncClient = orig
        asyncio.run(run())

    def test_unreachable_raises(self):
        async def run():
            from ontogram_backend import BackendError
            import ontogram_backend as ob
            def handler(request):
                raise httpx.ConnectError("down")
            orig = httpx.AsyncClient
            class FakeClient(orig):
                def __init__(self, *a, **k):
                    super().__init__(transport=httpx.MockTransport(handler), timeout=10.0)
            ob.httpx.AsyncClient = FakeClient
            try:
                with self.assertRaises(BackendError):
                    await detect_dialect("http://mock")
            finally:
                ob.httpx.AsyncClient = orig
        asyncio.run(run())


class TestAgentClientContract(unittest.TestCase):
    """agent_client.resolve_dataset must mirror the bridge's _resolve_dataset."""

    def test_parity(self):
        from agent_client import resolve_dataset
        cases = [
            (None, None, None, "u"),
            ("global", None, None, "u"),
            ("project", "p", None, "u"),
            ("session", "p", "s 1/x", "u"),
        ]
        for scope, p, s, u in cases:
            ds, uid = resolve_dataset(scope, p, s, u)

# live smoke against a running daemon
if os.environ.get("LIVE"):
    class TestLive(unittest.TestCase):
        def test_health_and_list(self):
            async def run():
                b = await create_backend(dialect="auto")
                self.assertTrue(await b.health())
                infos = await b.list_datasets()
                print(f"[live] dialect={b.dialect} datasets={len(infos)}")
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
