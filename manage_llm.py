#!/usr/bin/env /home/himanshu/builds/cognee/.venv/bin/python
"""
manage_llm.py - Cognee LLM & Provider Management Utility
Helps view, test, and update LiteLLM models, custom proxy endpoints, and environment settings for Cognee.
"""

import os
import sys
import argparse
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"

def load_env_dict(path: Path) -> dict:
    env_vars = {}
    if not path.exists():
        return env_vars
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip().strip('"').strip("'")
    return env_vars

def sync_env_to_os(env_vars: dict):
    for k, v in env_vars.items():
        if v:
            os.environ[k] = v
    # Set fallback environment variables for LiteLLM
    api_key = env_vars.get("LLM_API_KEY", "")
    if api_key and api_key != "YOUR_API_KEY_HERE":
        os.environ.setdefault("OPENAI_API_KEY", api_key)
        os.environ.setdefault("GEMINI_API_KEY", api_key)
        os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
        os.environ.setdefault("LITELLM_API_KEY", api_key)
    
    endpoint = env_vars.get("LLM_ENDPOINT", "")
    if endpoint:
        os.environ.setdefault("OPENAI_API_BASE", endpoint)
        os.environ.setdefault("GEMINI_API_BASE", endpoint)

def save_env_dict(path: Path, updates: dict):
    lines = []
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f'{key}="{updates[key]}"\n')
                updated_keys.add(key)
                continue
        new_lines.append(line)
        
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f'{key}="{val}"\n')
            
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print(f"✓ Updated {len(updates)} key(s) in {path.name}")

def print_status():
    env_vars = load_env_dict(ENV_PATH)
    print("\n--- Ontogram Provider Status (any OpenAI-compatible inference provider) ---")
    print(f"  LLM Provider      : {env_vars.get('LLM_PROVIDER', 'not set')}  (openai = any OpenAI-compatible, incl. opencode-go)")
    print(f"  LLM Model         : {env_vars.get('LLM_MODEL', 'not set')}")
    print(f"  LLM Endpoint      : {env_vars.get('LLM_ENDPOINT') or '[Default Cloud Direct: https://api.openai.com/v1]'}")
    print(f"  LLM API Key       : {'[Set]' if env_vars.get('LLM_API_KEY') and env_vars.get('LLM_API_KEY') != 'YOUR_API_KEY_HERE' else '[Not set / Default placeholder]'}")
    print(f"  Embedding Provider: {env_vars.get('EMBEDDING_PROVIDER', 'not set')}")
    print(f"  Embedding Model   : {env_vars.get('EMBEDDING_MODEL', 'not set')}")
    print(f"  Embedding Endpoint: {env_vars.get('EMBEDDING_ENDPOINT') or '[Default]'}")
    print(f"  Backend Port      : {env_vars.get('COGNEE_BACKEND_PORT', '8000')}")
    print(f"  Dashboard Port    : {env_vars.get('COGNEE_FRONTEND_PORT', '3000')}")
    print("  Note: Cognee internally uses LiteLLM library, but any OpenAI-compatible base URL works (opencode-go, OpenAI, etc.)")
    print("--------------------------------------\n")

def _strip_provider_prefix(model: str) -> str:
    """Any inference provider: strip litellm provider prefix (openai/, anthropic/) for raw OpenAI API."""
    if "/" in model:
        return model.split("/", 1)[1]
    return model

def test_direct_openai(model: str, api_key: str, endpoint: str = None):
    """Direct OpenAI-compatible test without LiteLLM — works with any inference provider (opencode-go, OpenAI, etc.)."""
    bare_model = _strip_provider_prefix(model)
    # endpoint is base like https://opencode.ai/zen/go/v1 ; append /chat/completions if needed
    if endpoint:
        base = endpoint.rstrip("/")
        if base.endswith("/chat/completions"):
            url = base
        elif base.endswith("/responses"):
            # muse-spark style — direct responses API
            url = base
        else:
            url = base + "/chat/completions"
    else:
        url = "https://api.openai.com/v1/chat/completions"
    print(f"Testing Direct OpenAI-compatible connection: '{bare_model}' -> {url}")
    try:
        import requests
        headers = {"Content-Type": "application/json"}
        if api_key and api_key != "YOUR_API_KEY_HERE":
            headers["Authorization"] = f"Bearer {api_key}"
        # responses vs chat payload
        if url.endswith("/responses"):
            payload = {"model": bare_model, "input": "Ping test for Ontogram direct connection."}
        else:
            payload = {"model": bare_model, "messages": [{"role": "user", "content": "Ping test for Ontogram direct connection."}], "max_tokens": 32}
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if r.status_code != 200:
            print(f"\n❌ Direct connection failed: HTTP {r.status_code}: {r.text[:600]}\n")
            return False
        data = r.json()
        # extract content for both APIs
        content = ""
        if "choices" in data and data["choices"]:
            content = data["choices"][0].get("message", {}).get("content", "") or data["choices"][0].get("text", "")
        elif "output" in data:
            # responses API
            content = str(data["output"][:1])
        print(f"\n✓ Direct Connection Successful!")
        print(f"Response: {str(content).strip()[:500]}\n")
        return True
    except Exception as e:
        print(f"\n❌ Direct connection failed: {e}\n")
        return False

def test_litellm_connection(model: str, api_key: str, endpoint: str = None):
    print(f"Testing LiteLLM model connection: '{model}' (Endpoint: {endpoint or 'default'})...")
    try:
        import litellm
        messages = [{"role": "user", "content": "Ping test for Cognee LiteLLM setup."}]
        kwargs = {"model": model, "messages": messages}
        if api_key and api_key != "YOUR_API_KEY_HERE":
            kwargs["api_key"] = api_key
        if endpoint:
            kwargs["api_base"] = endpoint
            kwargs["custom_llm_provider"] = "openai"
        response = litellm.completion(**kwargs)
        content = response.choices[0].message.content
        print(f"\n✓ LiteLLM Connection Successful!")
        print(f"Response: {content.strip()}\n")
        return True
    except Exception as e:
        print(f"\n❌ LiteLLM connection failed: {e}\n")
        return False

def test_connection(model: str, api_key: str, endpoint: str = None):
    """Provider-agnostic: try direct OpenAI-compatible first, fall back to LiteLLM if needed. Any inference provider works."""
    ok = test_direct_openai(model, api_key, endpoint=endpoint)
    if ok:
        return True
    print("Direct test failed, trying LiteLLM fallback (Cognee's internal path)...")
    return test_litellm_connection(model, api_key, endpoint=endpoint)

def main():
    parser = argparse.ArgumentParser(description="Manage Cognee LLM Providers & Settings")
    parser.add_argument("--status", action="store_true", help="Show current provider configuration")
    parser.add_argument("--set-model", type=str, help="Set LLM_MODEL (e.g. gemini/gemini-2.5-flash or openai/model-name)")
    parser.add_argument("--set-endpoint", type=str, help="Set custom LiteLLM base URL / endpoint")
    parser.add_argument("--set-key", type=str, help="Set LLM_API_KEY")
    parser.add_argument("--set-embedding-provider", type=str, help="Set EMBEDDING_PROVIDER (litellm or fastembed)")
    parser.add_argument("--set-embedding-endpoint", type=str, help="Set custom EMBEDDING_ENDPOINT URL")
    parser.add_argument("--test", action="store_true", help="Test current LiteLLM configuration")
    
    args = parser.parse_args()
    
    updates = {}
    if args.set_model:
        updates["LLM_MODEL"] = args.set_model
        updates["LLM_PROVIDER"] = "litellm"
    if args.set_endpoint is not None:
        updates["LLM_ENDPOINT"] = args.set_endpoint
    if args.set_key:
        updates["LLM_API_KEY"] = args.set_key
    if args.set_embedding_provider:
        updates["EMBEDDING_PROVIDER"] = args.set_embedding_provider
    if args.set_embedding_endpoint is not None:
        updates["EMBEDDING_ENDPOINT"] = args.set_embedding_endpoint
        
    if updates:
        save_env_dict(ENV_PATH, updates)
        
    env_vars = load_env_dict(ENV_PATH)
    sync_env_to_os(env_vars)
    
    if args.test:
        model = env_vars.get("LLM_MODEL", "gemini/gemini-2.5-flash")
        key = env_vars.get("LLM_API_KEY", "")
        endpoint = env_vars.get("LLM_ENDPOINT", "")
        test_connection(model, key, endpoint=endpoint)
    elif not updates or args.status:
        print_status()

if __name__ == "__main__":
    main()
