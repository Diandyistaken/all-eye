"""Yonlendirici: config'teki sirayla dener, ilk konusan kazanir."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from alleye import config
from alleye.brain.providers import REGISTRY, Provider, ProviderError


@dataclass
class Answer:
    text: str = ""
    provider: str = ""
    model: str = ""
    errors: list[str] = field(default_factory=list)


def _build(cfg: dict, only: str | None = None, deep: bool = False) -> list[Provider]:
    names = [only] if only else list(cfg.get("providers", []))
    out: list[Provider] = []
    for name in names:
        cls = REGISTRY.get(name)
        if cls is None:
            continue
        out.append(cls(cfg.get(name, {}), deep))
    return out


def available(cfg: dict | None = None) -> list[tuple[str, bool, str]]:
    """(isim, hazir_mi, sebep) - `alleye doctor` bunu basar."""
    cfg = cfg or config.load()
    rows = []
    for p in _build(cfg):
        ok, why = p.ready()
        rows.append((p.name, ok, why))
    return rows


class Router:
    def __init__(self, cfg: dict | None = None, only: str | None = None,
                 notify=None, deep: bool = False):
        self.cfg = cfg or config.load()
        self.providers = _build(self.cfg, only, deep)
        for p in self.providers:
            p.notify = notify

    def stream(self, system: str, user: str,
               image_png: bytes | None = None) -> Iterator[str]:
        """Cevabi parca parca akitir. Son parca sonrasi `self.used` doludur.

        image_png verilirse (Faz 3) yalniz gorsel destekleyen saglayicilar
        denenir; digerleri beklenmedik bir parametreyle cokmek yerine elenir.
        Hicbiri uygun degilse net bir hata verilir - sessizce metin-only
        gondermek kullaniciyi yaniltirdi (goruntuye baktigini sanir).
        """
        self.used = Answer()
        if not self.providers:
            raise ProviderError("hicbir saglayici tanimli degil (config.json > providers)")

        chain = self.providers
        if image_png is not None:
            chain = [p for p in chain if getattr(p, "supports_vision", False)]
            if not chain:
                raise ProviderError(
                    "goruntu destekleyen saglayici yok (su an yalniz gemini). "
                    "config.json > providers listesine gemini ekle.")

        for p in chain:
            ok, why = p.ready()
            if not ok:
                self.used.errors.append(f"{p.name}: {why}")
                continue
            try:
                first = True
                gen = (p.stream(system, user, image_png) if image_png is not None
                       else p.stream(system, user))
                for chunk in gen:
                    if first:
                        self.used.provider, first = p.name, False
                    self.used.text += chunk
                    yield chunk
                if not first:
                    self.used.model = p.model
                    return
                self.used.errors.append(f"{p.name}: bos cevap")
            except ProviderError as exc:
                self.used.errors.append(str(exc))
                continue

        raise ProviderError(
            "hicbir saglayici cevap veremedi:\n  - " + "\n  - ".join(self.used.errors)
        )

    def ask(self, system: str, user: str) -> Answer:
        for _ in self.stream(system, user):
            pass
        return self.used
