# Setup IA locale — à faire en rentrant au PC

Deux options. Le code s'en fiche : il parle l'API OpenAI-compatible dans les
deux cas, seul `.env` change.

---

## Option A — Laptop (RTX A3000 6 Go) · 5 minutes, démarre ce soir

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5vl:7b        # ~5 Go. Si trop lent: qwen2.5vl:3b
```

`.env` : rien à changer (défaut = `AI_URL=http://localhost:11434/v1`).

Test rapide :
```bash
curl http://localhost:11434/v1/chat/completions -d '{
  "model": "qwen2.5vl:7b",
  "messages": [{"role":"user","content":"Réponds en JSON: {\"ok\": true}"}]
}'
```

Limites honnêtes : 6 Go VRAM = q4 juste-juste (débordement RAM → plus lent),
et le laptop doit rester allumé 24/7.

---

## Option B — BC-250 16 Go · la maison permanente (une soirée de setup)

C'est un APU de PS5 (Zen2 + RDNA2, 16 Go GDDR6 unifiée). Excellent rapport
perf/prix pour l'IA locale, MAIS aucun support officiel : ni CUDA, ni ROCm.
La voie qui marche = **Vulkan + llama.cpp**. Communauté active, pièges connus :

### 1. BIOS
- Monter le partage mémoire GPU au max (« UMA Frame Buffer Size » → 8-12 Go).

### 2. OS
- **Fedora** (Mesa récent, c'est ce que la communauté BC-250 utilise).
- Piège n°1 : sans fix, le GPU reste bloqué à basse fréquence.
  Installer le gouverneur communautaire **oberon-governor**
  (github — chercher "oberon-governor bc-250"), puis vérifier avec
  `vulkaninfo | grep deviceName` que le GPU (gfx1013) est vu.
- Bonus : ce fix ramène l'idle à ~35-50 W (sinon ~90 W). Compte 5-10 €/mois
  d'électricité en 24/7.

### 3. llama.cpp (serveur IA)
```bash
sudo dnf install -y git cmake gcc-c++ vulkan-devel glslc
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DGGML_VULKAN=ON && cmake --build build -j
```

Modèle (vision, 2 fichiers requis — le GGUF + le projecteur mmproj) :
```bash
# ggml-org/Qwen2.5-VL-7B-Instruct-GGUF sur Hugging Face
llama-server -hf ggml-org/Qwen2.5-VL-7B-Instruct-GGUF:Q8_0 \
  --host 0.0.0.0 --port 8080 -ngl 99
```
Avec 16 Go tu peux te payer le Q8 (meilleur que le q4 du laptop).
Alternative si tu veux tester mieux en français : `gemma-3-12b-it` (vision
aussi, ~8 Go en q4).

### 4. Service systemd (démarre tout seul)
```ini
# /etc/systemd/system/llama.service
[Unit]
Description=llama-server IA locale
After=network.target
[Service]
ExecStart=/home/USER/llama.cpp/build/bin/llama-server -hf ggml-org/Qwen2.5-VL-7B-Instruct-GGUF:Q8_0 --host 0.0.0.0 --port 8080 -ngl 99
Restart=always
[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now llama`

### 5. Côté scanner (laptop ou le BC-250 lui-même)
`.env` :
```
AI_URL=http://IP_DU_BC250:8080/v1
```
(le scanner Leboncoin peut aussi tourner SUR le BC-250 : c'est un Zen2
6 cœurs, largement assez — tout-en-un, laptop libéré.)

---

## Reco

1. **Ce soir** : Option A, le scanner commence à apprendre le marché.
2. **Ce week-end** : Option B, bascule `AI_URL`, éteins Ollama du laptop.
3. À terme : scanner + IA ensemble sur le BC-250, ton laptop redevient libre.
