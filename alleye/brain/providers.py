"""Saglayicilar. Hepsi ayni arayuz: stream(system, user) -> metin parcalari."""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator

from alleye.brain.http import HttpError, get_json, stream_ndjson, stream_sse


class ProviderError(RuntimeError):
    pass


class Provider:
    name = "?"
    supports_vision = False   # Faz 3: goruntu kabul eden saglayici mi

    def __init__(self, cfg: dict, deep: bool = False):
        self.cfg = cfg
        key = "models_deep" if deep and cfg.get("models_deep") else "models"
        self.models: list[str] = list(cfg.get(key) or [])
        self.model = self.models[0] if self.models else ""
        self.notify = None  # Callable[[str], None] - ilerleme bildirimi

    def _say(self, text: str) -> None:
        if self.notify is not None:
            self.notify(text)

    def ready(self) -> tuple[bool, str]:
        raise NotImplementedError

    def stream(self, system: str, user: str) -> Iterator[str]:
        raise NotImplementedError

    def _key(self) -> str:
        return os.environ.get(self.cfg.get("api_key_env", ""), "").strip()

    def _key_ready(self) -> tuple[bool, str]:
        """Anahtar var mi VE formati tutuyor mu. Ikisi ayri sorun, ayri mesaj."""
        from alleye.config import key_is_usable, key_looks_wrong

        env = self.cfg.get("api_key_env", "")
        key = self._key()
        if not key:
            return False, f"{env} tanimli degil"
        if not key_is_usable(env, key):
            return False, key_looks_wrong(env, key) or f"{env} formati taninmiyor"
        return True, ""


class Gemini(Provider):
    """Google AI Studio ucretsiz katmani - gorsel dahil, kart istemiyor.

    Kimlik dogrulama `x-goog-api-key` BASLIGI ile yapilir, URL'deki ?key= ile
    degil. Google 2026'da anahtar formatini degistirdi: eski "Standard" anahtarlar
    (AIza...) yerini servis hesabina bagli "Auth" anahtarlarina (AQ.Ab...) birakti
    ve Eylul 2026'dan sonra AIza anahtarlari tamamen reddedilecek. AQ anahtarlari
    eski ?key= yontemiyle calismaz - baslik ikisiyle de calisir.
    """

    name = "gemini"
    supports_vision = True   # ucretsiz katmanda gorsel dahil
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def ready(self) -> tuple[bool, str]:
        return self._key_ready()

    def stream(self, system: str, user: str,
               image_png: bytes | None = None) -> Iterator[str]:
        key = self._key()
        if not key:
            raise ProviderError("gemini: anahtar yok")
        # Goruntu varsa inlineData olarak ayni user mesajina eklenir. image_png
        # None ise payload eskisiyle BIREBIR ayni kalir - metin yolu bozulmaz.
        parts: list[dict] = [{"text": user}]
        if image_png:
            parts.append({"inlineData": {
                "mimeType": "image/png",
                "data": base64.b64encode(image_png).decode("ascii"),
            }})
        payload_base = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1600},
        }
        headers = {"x-goog-api-key": key}
        # Goruntulu istek daha buyuk govde + daha cok token; zaman asimi genis.
        timeout = 90.0 if image_png else 45.0
        trail: list[str] = []
        for model in self.models:
            url = f"{self.BASE}/{model}:streamGenerateContent?alt=sse"
            self._say(f"gemini · {model} dusunuyor")
            try:
                got = False
                for obj in stream_sse(url, payload_base, headers, timeout):
                    for cand in obj.get("candidates", []):
                        for part in cand.get("content", {}).get("parts", []):
                            text = part.get("text")
                            if text:
                                got = True
                                yield text
                if got:
                    self.model = model
                    return
                trail.append(f"{model}: bos cevap")
                self._say(f"gemini · {model} bos dondu, sonraki")
            except HttpError as exc:
                trail.append(f"{model}: {exc.status} {exc.message[:110]}")
                # 404 model emekli, 429 o modelin kotasi bitti, 503 gecici yuk.
                # Hepsinde bir sonraki modeli denemek dogru; kimlik hatasinda degil.
                # 0 = zaman asimi / baglanti hatasi; o da sonraki modeli hak eder.
                if exc.status in (0, 400, 404, 429, 503):
                    self._say(f"gemini · {model} → {exc.status}, sonraki model")
                    continue
                break
        raise ProviderError("gemini:\n      " + "\n      ".join(trail or ["cevap yok"]))


class OpenAICompat(Provider):
    """Groq ve OpenAI-uyumlu her sey (OpenRouter, Cerebras, yerel vLLM...)."""

    name = "openai-compat"
    url = ""

    def ready(self) -> tuple[bool, str]:
        return self._key_ready()

    def stream(self, system: str, user: str) -> Iterator[str]:
        key = self._key()
        if not key:
            raise ProviderError(f"{self.name}: anahtar yok")
        headers = {"Authorization": f"Bearer {key}"}
        trail: list[str] = []
        for model in self.models:
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": 0.3,
                "max_tokens": 1600,
                "stream": True,
            }
            try:
                got = False
                for obj in stream_sse(self.url, payload, headers):
                    for ch in obj.get("choices", []):
                        text = (ch.get("delta") or {}).get("content")
                        if text:
                            got = True
                            yield text
                if got:
                    self.model = model
                    return
                trail.append(f"{model}: bos cevap")
            except HttpError as exc:
                trail.append(f"{model}: {exc.status} {exc.message[:110]}")
                # 0 = zaman asimi / baglanti hatasi; o da sonraki modeli hak eder.
                if exc.status in (0, 400, 404, 429, 503):
                    continue
                break
        raise ProviderError(f"{self.name}:\n      " + "\n      ".join(trail or ["cevap yok"]))


class Groq(OpenAICompat):
    name = "groq"
    url = "https://api.groq.com/openai/v1/chat/completions"


class OpenRouter(OpenAICompat):
    name = "openrouter"
    url = "https://openrouter.ai/api/v1/chat/completions"


class Ollama(Provider):
    """Cevrimdisi / gizli is icin yerel yedek. Sadece ihtiyac aninda uyanir."""

    name = "ollama"

    def __init__(self, cfg: dict, deep: bool = False):
        super().__init__(cfg, deep)
        self.host = cfg.get("host", "http://127.0.0.1:11434").rstrip("/")

    def ready(self) -> tuple[bool, str]:
        try:
            data = get_json(f"{self.host}/api/tags", timeout=1.5)
        except HttpError:
            return False, "ollama calismiyor (ollama serve)"
        names = {m.get("name", "") for m in (data or {}).get("models", [])}  # type: ignore[union-attr]
        if not names:
            return False, "ollama'da hic model yok"
        for m in self.models:
            if m in names or any(n.startswith(m.split(":")[0]) for n in names):
                return True, ""
        return False, f"model indirilmemis: ollama pull {self.models[0]}"

    def stream(self, system: str, user: str) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": True,
            "options": {"temperature": 0.3, "num_ctx": 8192},
        }
        try:
            for obj in stream_ndjson(f"{self.host}/api/chat", payload, {}):
                text = (obj.get("message") or {}).get("content")
                if text:
                    yield text
                if obj.get("done"):
                    return
        except HttpError as exc:
            raise ProviderError(f"ollama: {exc}") from None


REGISTRY: dict[str, type[Provider]] = {
    "gemini": Gemini,
    "groq": Groq,
    "openrouter": OpenRouter,
    "ollama": Ollama,
}
