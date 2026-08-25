"""
Provider-agnostic LLM client. Behavior is controlled entirely by .env, so
switching machines (or switching Groq <-> Ollama) never requires touching
this file -- only .env.

NOTE: functionally unchanged in this revision -- every other pipeline module
(analyze.py, scoring.py) still calls get_llm_json()/get_llm_response() the
same way. Listed here mainly so the whole pipeline ships as one consistent
set of files.

.env keys:
    LLM_PROVIDER   "auto" (default, Groq then Ollama fallback) | "groq" | "ollama"
    GROQ_API_KEY   required if LLM_PROVIDER is "auto" or "groq"
    GROQ_MODEL     default: openai/gpt-oss-120b
    OLLAMA_URL     default: http://localhost:11434/api/generate
    OLLAMA_MODEL   default: llama3.2:3b

Setup:
    Groq:   export GROQ_API_KEY="your-key-here"   (free tier: https://console.groq.com)
            pip install groq
    Ollama: install from https://ollama.com, then in a terminal:
                ollama pull llama3.2:3b
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()  # reads .env in the repo root and sets os.environ -- run this once at import time

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto").lower()  # "auto" | "groq" | "ollama"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")  # llama-3.3-70b-versatile was deprecated by Groq (Aug 2026)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")

# Sieg 23/08 -- list of available Groq keys, in try-order. Empty/unset
# GROQ_API_KEY_2 is simply skipped, so this is safe with only 1 key too.
# Sieg 24/08 -- temporarily disabled, going back to a single key. Kept the
# original list commented instead of deleted so it's a one-line swap to
# turn rotation back on later.
# GROQ_KEYS = [k for k in (
#     os.environ.get("GROQ_API_KEY"),
#     os.environ.get("GROQ_API_KEY_2"),
# ) if k]
GROQ_KEYS = [os.environ.get("GROQ_API_KEY")] if os.environ.get("GROQ_API_KEY") else []

def _is_rate_limit_error(e):
    """Sieg 23/08 -- detects a 429/quota error specifically, so we only
    rotate keys for THAT reason (not for e.g. a malformed prompt, which
    would just fail the same way on the second key)."""
    msg = str(e).lower()
    return "429" in msg or "rate_limit" in msg or "quota" in msg


def _call_groq(prompt, system_prompt=None):
    from groq import Groq  # imported lazily so the package is only required if used

    if not GROQ_KEYS:
        raise RuntimeError("GROQ_API_KEY not set")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # Sieg 23/08 -- try each key in turn; on a rate-limit error, move to the
    # next key instead of failing straight to Ollama. Any OTHER error (bad
    # key, network issue) still raises immediately -- no point retrying that
    # on a second key.
    # Sieg 24/08 -- rotation loop disabled (single key in use again). Kept
    # commented, not deleted, so re-enabling it later is a one-line swap
    # (just uncomment this block and delete the single-key call below it).
    # last_error = None
    # for i, api_key in enumerate(GROQ_KEYS):
    #     try:
    #         client = Groq(api_key=api_key)
    #         response = client.chat.completions.create(
    #             model=GROQ_MODEL,
    #             messages=messages,
    #             temperature=0,
    #         )
    #         return response.choices[0].message.content
    #     except Exception as e:
    #         last_error = e
    #         if _is_rate_limit_error(e) and i < len(GROQ_KEYS) - 1:
    #             print(f"[llm_client] Groq key #{i + 1} rate-limited, trying key #{i + 2}")
    #             continue
    #         raise  # not a rate-limit error, or no more keys left -- propagate
    # raise last_error

    # Single-key call (no rotation): just use the one key we have.
    client = Groq(api_key=GROQ_KEYS[0])
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0,
    )
    return response.choices[0].message.content


def _call_ollama(prompt, system_prompt=None):
    import requests  # already a dependency of pipeline/ingest.py

    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    resp = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": full_prompt, "stream": False},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["response"]


def get_llm_response(prompt, system_prompt=None):
    """
    Provider selection driven by LLM_PROVIDER in .env:
      - "ollama": call Ollama only, never touch Groq.
      - "groq":   call Groq only, no fallback (fails loudly if unavailable).
      - "auto" (default): try Groq first, fall back to Ollama on any failure
        (quota, network, auth) -- this is also what happens automatically
        if GROQ_API_KEY is simply left empty in .env.
    """
    if LLM_PROVIDER == "ollama":
        return _call_ollama(prompt, system_prompt)
    if LLM_PROVIDER == "groq":
        return _call_groq(prompt, system_prompt)
    try:
        return _call_groq(prompt, system_prompt)
    except Exception as e:
        print(f"[llm_client] Groq failed ({e}), falling back to Ollama")
        return _call_ollama(prompt, system_prompt)


def get_llm_json(prompt, system_prompt=None):
    """
    Same as get_llm_response, but strips markdown code fences and parses JSON.
    Use this whenever you need a structured {"score": ..., "justification": ...}
    output -- e.g. for scoring/scoring.py's evidence_quality and
    strategic_relevance functions.
    Returns None if parsing fails (caller should handle that case).
    """
    try:
        raw = get_llm_response(prompt, system_prompt)
    except Exception as e:
        print(f"[llm_client] No LLM reachable ({e}) -- check GROQ_API_KEY or Ollama")
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        print(f"[llm_client] Could not parse JSON from response: {raw[:200]}")
        return None


if __name__ == "__main__":
    # Quick manual test: python -m llm.llm_client
    print(f"[llm_client] provider={LLM_PROVIDER}  groq_model={GROQ_MODEL}  ollama_model={OLLAMA_MODEL}")
    result = get_llm_response("Reply with exactly the word: OK")
    print("LLM responded:", result)