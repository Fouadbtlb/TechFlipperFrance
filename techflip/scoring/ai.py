"""Local vision model (multimodal): runs on deal candidates only.

One call per deal: description + up to N photos → structured verdict
(visible defects, text/photo incoherences, scam risk). Zero external deps
(stdlib urllib); if the AI server is down or slow, the alert still fires
without this stage. Never blocking, never required.

Speaks the OpenAI-compatible chat API, so the backend is swappable via .env:
- Ollama on the laptop        → AI_URL=http://localhost:11434/v1
- llama-server on the BC-250  → AI_URL=http://<ip-bc250>:8080/v1
"""
from __future__ import annotations

import base64
import json
import logging
import re
import urllib.request

from ..domain import Listing

log = logging.getLogger(__name__)

_PROMPT = """Tu es un expert achat-revente de materiel electronique d'occasion.
REGARDE D'ABORD LES PHOTOS. Le titre et la description sont des affirmations du
vendeur qui PEUVENT ETRE FAUSSES (appat classique: titrer "PS5" une PS4). Identifie
ce que tu VOIS reellement sur les photos, pas ce qui est ecrit.

TITRE (a verifier, peut mentir): {title}
PRIX: {price} €
DESCRIPTION (a verifier):
{description}

Reponds en JSON strict:
{{
  "type": "pc|console|gpu|cpu|ram|storage|psu|motherboard|controller|game|monitor|laptop|phone|accessory|other",
  "condition": "working|broken",
  "components": [
    {{"type": "gpu|cpu|ram|storage|psu|motherboard|console|controller|game|monitor", "model": "<le modele que tu VOIS sur la photo: ex PS4 Slim, RTX 4070, 16Go DDR4, DualSense>", "qty": <entier>}}
  ],
  "photo_correspond_au_titre": <true/false>,
  "is_trade": <true/false>,
  "valeur_revente_rapide": <entier EUR, UNIQUEMENT si type laptop/phone/other non decomposable>,
  "risque_arnaque": <entier 0-10>
}}
REGLES:
- "components": identifie le materiel d'apres sa FORME sur les photos. PS5 = grande, blanche, verticale, incurvee. PS4/PS4 Slim = petite, noire, plate. Xbox Series X = grande tour noire, Series S = petite blanche. Manette DualShock 4 (PS4) a une barre lumineuse; DualSense (PS5) est plus grosse et bicolore. Pour un GPU/CPU, lis le modele sur l'autocollant ou la boite si visible; sinon ne DEVINE PAS un modele precis.
- N'inclus dans "components" que ce qui est reellement inclus/visible, article principal compris. Pas ce qui est juste cite pour comparaison/compatibilite ("compatible PS5", "mieux qu'une RTX 3050"). Accessoire/jeu/support seul: components vide.
- "photo_correspond_au_titre": false si ce que tu vois ne correspond pas au titre (ex titre PS5 mais photo d'une PS4, titre RTX 4070 mais autre carte). Dans ce cas mets "risque_arnaque" >= 8.
- "type" par article: une manette = controller (jamais console). Un jeu = game. Un ecran = monitor.
- "condition": "broken" si HS, en panne, pour pieces, ne s'allume plus.
- "valeur_revente_rapide": prix de revente rapide d'OCCASION (jamais neuf). Surtout pour PC portables/telephones non decomposables. Sous-estime dans le doute.
- "is_trade": true si echange ou faux prix d'appel (1€).
- "risque_arnaque": titre trompeur, prix trop bas inexplique, compte/iCloud verrouille, ex-minage, boite/coque seule au prix du produit, pins tordus.
"""


class AIVetter:
    def __init__(
        self,
        url: str = "http://localhost:11434/v1",
        model: str = "qwen2.5vl:7b",
        max_images: int = 4,
        timeout: float = 240.0,
    ):
        self.url = url.rstrip("/")
        self.model = model
        self.max_images = max_images
        self.timeout = timeout

    def classify(self, l: Listing) -> dict | None:
        """One model call on the description + photos -> structured verdict
        (components seen, condition, scam risk). Raises on transport errors;
        the caller decides what a failure means."""
        images = self._download_images(l.image_urls[: self.max_images])
        return parse_verdict(self._chat(self._prompt(l), images)) or None

    def _prompt(self, l: Listing) -> str:
        return _PROMPT.format(
            title=l.title,
            price=f"{l.price:,.0f}".replace(",", " "),
            description=(l.description or "(vide)")[:1500],
        )

    def _chat(self, prompt: str, images: list[str]) -> str:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for b64 in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "temperature": 0.1,
            "max_tokens": 500,
        }).encode()
        req = urllib.request.Request(
            f"{self.url}/chat/completions", data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            log.warning("vision model HTTP %s: %s", e.code, e.read()[:300])
            raise

    def _download_images(self, urls: tuple[str, ...]) -> list[str]:
        out = []
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    out.append(base64.b64encode(resp.read()).decode())
            except Exception:
                log.debug("image download failed: %s", u)
        return out


# ---------- pure, testable ----------

def parse_verdict(raw: str) -> dict:
    """Lenient JSON extraction (models sometimes fence or pad output)."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        d = json.loads(m.group()) if m else {}
    return d if isinstance(d, dict) else {}
