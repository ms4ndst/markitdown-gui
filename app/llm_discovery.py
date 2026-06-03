"""Discover locally running OpenAI-compatible LLM servers and their models.

Probes the standard ports used by LM Studio, Ollama, vLLM, llama.cpp server
and similar projects. Each is asked for ``GET /v1/models`` (the OpenAI-API
standard endpoint), and the returned model list is filtered to those whose
identifier matches a known vision-capable pattern.

Vision detection is name-based — the OpenAI /models endpoint doesn't expose a
``vision`` flag and Ollama's tags endpoint doesn't either. New vision models
appear constantly, so add their tokens to ``VISION_PATTERNS`` as needed.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from urllib.error import URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class ProviderPreset:
    """One-click endpoint + model + key-acquisition hint for a vision LLM provider."""
    name: str
    endpoint: str
    model: str
    hint: str = ""


# Order shown in the GUI dropdown. "Custom" stays at index 0 (no-op).
PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        name="Custom",
        endpoint="",
        model="",
    ),
    ProviderPreset(
        name="OpenAI",
        endpoint="https://api.openai.com/v1",
        model="gpt-4o",
        hint="Paid — get a key at https://platform.openai.com/api-keys",
    ),
    ProviderPreset(
        name="Google Gemini",
        endpoint="https://generativelanguage.googleapis.com/v1beta/openai/",
        model="gemini-2.0-flash",
        hint="Free tier — get a key at https://aistudio.google.com/apikey",
    ),
    ProviderPreset(
        name="Groq",
        endpoint="https://api.groq.com/openai/v1",
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        hint="Free tier — get a key at https://console.groq.com/keys",
    ),
    ProviderPreset(
        name="OpenRouter",
        endpoint="https://openrouter.ai/api/v1",
        model="google/gemini-2.0-flash-exp:free",
        hint="Has free models — get a key at https://openrouter.ai/keys",
    ),
    ProviderPreset(
        name="Mistral",
        endpoint="https://api.mistral.ai/v1",
        model="pixtral-12b-2409",
        hint="Free 'Experiment' tier — get a key at https://console.mistral.ai/api-keys",
    ),
    ProviderPreset(
        name="Azure OpenAI",
        endpoint="https://YOUR-RESOURCE.openai.azure.com/openai/v1",
        model="gpt-4o",
        hint=(
            "Replace YOUR-RESOURCE in the URL with your Azure resource name. "
            "Use the deployment name as the model. Key is the resource API key."
        ),
    ),
    ProviderPreset(
        name="LM Studio (local)",
        endpoint="http://localhost:1234/v1",
        model="",
        hint="No key needed — start LM Studio's Local Server and load a vision model.",
    ),
    ProviderPreset(
        name="Ollama (local)",
        endpoint="http://localhost:11434/v1",
        model="",
        hint="No key needed — run 'ollama serve' and pull a vision model "
             "(e.g. 'ollama pull moondream').",
    ),
)


# (label, base URL) — order is the discovery order shown to the user.
KNOWN_LOCAL_ENDPOINTS: list[tuple[str, str]] = [
    ("LM Studio", "http://localhost:1234/v1"),
    ("Ollama", "http://localhost:11434/v1"),
    ("vLLM", "http://localhost:8000/v1"),
    ("llama.cpp server", "http://localhost:8080/v1"),
    ("Text Generation WebUI", "http://localhost:5000/v1"),
]


# Case-insensitive substrings of model IDs that indicate vision capability.
# Conservative on purpose — false positives waste a real LLM call to find out.
VISION_PATTERNS: tuple[str, ...] = (
    # OpenAI
    "gpt-4o", "gpt-4-vision", "gpt-4-turbo", "gpt-5", "o1", "o3",
    "chatgpt-4o",
    # Anthropic (via proxy)
    "claude-3", "claude-4", "claude-opus", "claude-sonnet", "claude-haiku",
    # Google
    "gemini", "gemma-3", "gemma3",
    # Meta (vision variants only)
    "llama-3.2-11b-vision", "llama-3.2-90b-vision", "llama3.2-vision",
    "llama-3.2-vision", "llama-4",
    # Alibaba
    "qwen-vl", "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "qwen2.5-omni",
    # OpenGVLab
    "internvl", "internlm-xcomposer",
    # Vikhyatk
    "moondream",
    # OpenBMB
    "minicpm-v", "minicpm-llama3-v", "minicpm-o",
    # Mistral
    "pixtral",
    # AllenAI
    "molmo",
    # Microsoft
    "phi-3-vision", "phi-3.5-vision", "phi-4-multimodal",
    # LLaVA family
    "llava", "bakllava", "obsidian",
    # Zhipu / others
    "cogvlm", "cogagent", "glm-4v",
    # 01.AI
    "yi-vl",
    # DeepSeek
    "deepseek-vl",
    # Reka
    "reka-",
    # Generic markers a packager might use
    "-vl-", "-vision", "-multimodal", "vlm",
)


def is_vision_model(model_id: str) -> bool:
    """Return True when ``model_id`` matches any known vision-capable pattern."""
    if not model_id:
        return False
    lower = model_id.lower()
    return any(p in lower for p in VISION_PATTERNS)


@dataclass
class LocalServer:
    name: str
    base_url: str
    models: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def is_running(self) -> bool:
        return not self.error

    def vision_models(self) -> list[str]:
        return [m for m in self.models if is_vision_model(m)]

    def __str__(self) -> str:
        if self.error:
            return f"{self.name}: not reachable"
        n_vision = len(self.vision_models())
        return f"{self.name} ({len(self.models)} models, {n_vision} vision)"


def probe_endpoint(name: str, base_url: str, timeout: float = 1.5) -> LocalServer:
    url = base_url.rstrip("/") + "/models"
    try:
        req = Request(url, headers={"Authorization": "Bearer not-needed"})
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        data = json.loads(body)
        raw = data.get("data", []) if isinstance(data, dict) else []
        ids = sorted({m.get("id") for m in raw if isinstance(m, dict) and m.get("id")})
        return LocalServer(name=name, base_url=base_url, models=list(ids))
    except URLError as exc:
        return LocalServer(name=name, base_url=base_url, error=str(exc.reason))
    except Exception as exc:
        return LocalServer(name=name, base_url=base_url, error=str(exc))


def discover_local_servers(timeout: float = 1.5) -> list[LocalServer]:
    """Probe every known endpoint in parallel and return results in fixed order."""
    with ThreadPoolExecutor(max_workers=len(KNOWN_LOCAL_ENDPOINTS)) as pool:
        futures = {
            pool.submit(probe_endpoint, name, url, timeout): (name, url)
            for name, url in KNOWN_LOCAL_ENDPOINTS
        }
        results: dict[str, LocalServer] = {}
        for fut in futures:
            name, url = futures[fut]
            try:
                results[url] = fut.result(timeout=timeout * 2)
            except Exception as exc:
                results[url] = LocalServer(name=name, base_url=url, error=str(exc))
    return [results[u] for _, u in KNOWN_LOCAL_ENDPOINTS]


class LocalLLMDiscovery(QObject):
    """Run ``discover_local_servers`` off the UI thread."""

    finished = Signal(list)  # list[LocalServer]

    def __init__(self) -> None:
        super().__init__()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="llm-discover"
        )

    def submit(self) -> None:
        future = self._executor.submit(discover_local_servers)
        future.add_done_callback(self._on_done)

    def _on_done(self, future: Future) -> None:
        try:
            servers = future.result()
        except Exception:
            servers = []
        self.finished.emit(servers)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
