import time

from techflip.domain import Listing
from techflip.scoring.ai import AIVetter

v = AIVetter(url="http://localhost:11434/v1", model="qwen2.5vl:7b", max_images=0, timeout=180)
l = Listing(
    source="lbc", source_id="1", url="u",
    title="PC Portable Gamer Lenovo Legion 5 Ryzen 7 5800H RTX 3060 16Go 512Go",
    price=650, published_at="now",
    description=("Vends mon PC portable gamer Lenovo Legion 5, tres bon etat, RTX 3060 "
                 "mobile, Ryzen 7 5800H, 16Go RAM DDR4, SSD 512Go, ecran 165Hz. "
                 "Fonctionne parfaitement, jamais de probleme. Envoi possible."),
    city="Lille", zipcode="59000",
)
t = time.time()
verdict = v.classify(l)
print(f"--- VERDICT ({time.time() - t:.1f}s) ---")
print(verdict)
