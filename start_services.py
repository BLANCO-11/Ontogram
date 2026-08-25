#!/usr/bin/env python3
"""
start_services.py - Cognee Core Memory Service Orchestrator
Launches the FastAPI REST backend (port 9480) for AI Agent integrations.
"""

import os
import sys
import time
import socket
import signal
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"

def load_env():
    """Load .env as *fallback defaults*: variables already present in the
    environment (e.g. injected by docker-compose env_file) always win."""
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

processes = []

def cleanup(signum=None, frame=None):
    print("\nShutting down Cognee services...")
    for p in processes:
        if hasattr(p, "poll") and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
    print("✓ All services stopped.")
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    
    load_env()
    backend_port = int(os.getenv("COGNEE_BACKEND_PORT", "9480"))
    mcp_port = int(os.getenv("COGNEE_MCP_PORT", "9481"))
    mcp_transport = os.getenv("COGNEE_MCP_TRANSPORT", "http")
    # Loopback by default: memory is personal. Set COGNEE_BIND_HOST=0.0.0.0
    # deliberately (and set ONTOGRAM_TOKEN) to expose beyond localhost.
    bind_host = os.getenv("COGNEE_BIND_HOST", "127.0.0.1")

    print("==================================================")
    print("       Cognee Core Agent Memory Engine            ")
    print("==================================================")

    # Start REST API Backend
    if is_port_in_use(backend_port):
        print(f"⚠️  Backend port {backend_port} is already active.")
    else:
        print(f"🚀 Starting Backend REST API Server on {bind_host}:{backend_port}...")
        backend_cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "cognee.api.client:app",
            "--host",
            bind_host,
            "--port",
            str(backend_port),
        ]
        p_backend = subprocess.Popen(backend_cmd, cwd=str(BASE_DIR))
        processes.append(p_backend)
        if p_backend.poll() is not None:
            print("❌ Backend failed to start.")
            sys.exit(1)
        # Wait for the daemon to actually accept connections before starting
        # the MCP bridge, so early tool calls don't hit a dead proxy target.
        for _ in range(60):  # up to ~60s (cognee imports are heavy on cold start)
            if is_port_in_use(backend_port):
                break
            if p_backend.poll() is not None:
                print("❌ Backend failed to start.")
                sys.exit(1)
            time.sleep(1)
        else:
            print(f"⚠️  Backend did not accept connections within 60s; continuing anyway.")
        print(f"✓ Backend running at http://{bind_host}:{backend_port} (Docs: http://localhost:{backend_port}/docs)")

    # Start the agent-agnostic Memory MCP server (proxies to the REST backend
    # so exactly one Cognee process holds the databases -> no write-lock races).
    if is_port_in_use(mcp_port):
        print(f"⚠️  MCP port {mcp_port} is already active.")
    else:
        print(f"🚀 Starting Memory MCP Server ({mcp_transport}) on {bind_host}:{mcp_port}...")
        mcp_env = os.environ.copy()
        mcp_env.setdefault("COGNEE_API_URL", f"http://localhost:{backend_port}")
        mcp_env["COGNEE_MCP_HOST"] = bind_host
        mcp_env["COGNEE_MCP_PORT"] = str(mcp_port)
        mcp_cmd = [
            sys.executable,
            str(BASE_DIR / "cognee_mcp_server.py"),
            "--transport",
            mcp_transport,
        ]
        p_mcp = subprocess.Popen(mcp_cmd, cwd=str(BASE_DIR), env=mcp_env)
        processes.append(p_mcp)
        time.sleep(2)
        if p_mcp.poll() is not None:
            print("❌ MCP server failed to start.")
            cleanup()
        print(f"✓ Memory MCP running at http://{bind_host}:{mcp_port}/mcp")

    # Information Summary
    print("\n--- Cognee Agent Memory Status Summary ---")
    print(f"  • REST API Backend : http://localhost:{backend_port}")
    print(f"  • Interactive Docs : http://localhost:{backend_port}/docs")
    print(f"  • Graph Visualizer : http://localhost:{backend_port}/api/v1/visualize")
    print(f"  • Memory MCP (HTTP): http://localhost:{mcp_port}/mcp")
    print("------------------------------------------\n")
    
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
