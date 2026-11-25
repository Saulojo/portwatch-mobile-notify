"""
PortWatch VI -> Telegram

Monitora https://portwatch-vi.xyz e manda uma mensagem no Telegram sempre que a
porcentagem do projeto mais perto de ser jogavel (o "lider") mudar, ou quando o
lider passar a ser outro projeto.

Usa apenas a biblioteca padrao do Python (nada para instalar).

Uso:
    python portwatch_notify.py               # roda em loop (padrao: checa a cada 5 min)
    python portwatch_notify.py --once        # checa uma vez e sai (bom pro Agendador de Tarefas)
    python portwatch_notify.py --test        # manda o status atual agora, mesmo sem mudanca
    python portwatch_notify.py --get-chat-id # mostra o seu chat_id (mande /start pro bot antes)
    python portwatch_notify.py --dry-run     # imprime a mensagem no terminal, sem enviar
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_URL = "https://portwatch-vi.xyz"
DATA_URL = BASE_URL + "/data/tracker.json"
HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.json"
STATE_FILE = HERE / "state.json"
USER_AGENT = "portwatch-notify/1.0"

# --------------------------------------------------------------------------------------
# Modelo de pontuacao: copia fiel de https://portwatch-vi.xyz/assets/js/scoring.js
# (o site nao guarda a porcentagem pronta; ele calcula a partir dos campos de cada projeto)
# --------------------------------------------------------------------------------------

MILESTONES = [
    ("groundwork", "Preparação", 0),
    ("loads", "Exe rodando", 10),
    ("boots", "Primeiro frame", 20),
    ("menu", "Menu principal", 30),
    ("world", "No mundo", 40),
    ("playable", "Jogável", 50),
    ("complete", "Completo", 100),
]
TICK = {k: at for k, _, at in MILESTONES}
MILESTONE_LABEL = {k: label for k, label, _ in MILESTONES}
LADDER = ["loads", "boots", "menu", "world", "playable"]

TRACK_WEIGHTS = {"story": 0.35, "render": 0.25, "perf": 0.2, "stability": 0.2}
STORY_STEPS = [
    (0, "Preso no início"),
    (0.1, "Prólogo concluído"),
    (0.25, "Primeiras missões"),
    (0.4, "Primeiro ato"),
    (0.6, "Metade da história"),
    (0.85, "História principal até os créditos"),
    (1, "100% concluído"),
]
RENDER_STEPS = [
    (0, "Preto ou quebrado"),
    (0.25, "Formas desenhadas, quase sem luz ou pretas"),
    (0.5, "Iluminado, mas faltam efeitos importantes"),
    (0.75, "Quase igual ao console, falhas pequenas"),
    (1, "Igual ao console"),
]
GROUNDWORK_WEIGHTS = {"loader": 0.2, "shaders": 0.28, "graphics": 0.32, "proven": 0.2}
STABILITY = {
    "unknown": ("Desconhecida", 0),
    "constant": ("Trava o tempo todo", 0),
    "often": ("Trava com frequência", 0.25),
    "sometimes": ("Trava às vezes", 0.55),
    "rarely": ("Raramente trava", 0.8),
    "stable": ("Estável", 1),
}


def _num(v) -> float | None:
    if isinstance(v, bool):
        return float(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def clamp01(v) -> float:
    f = _num(v)
    return 0.0 if f is None else min(1.0, max(0.0, f))


def ladder_value(v) -> float:
    if v is True:
        return 1.0
    if v is False or v is None:
        return 0.0
    return clamp01(v)


def groundwork_fraction(gw) -> float:
    gw = gw or {}
    return sum(w * clamp01(gw.get(k)) for k, w in GROUNDWORK_WEIGHTS.items())


def track_values(gta: dict) -> dict:
    st = gta.get("stability")
    if isinstance(st, (int, float)) and not isinstance(st, bool):
        stab = clamp01(st)
    else:
        stab = STABILITY.get(st, STABILITY["unknown"])[1]
    return {
        "story": clamp01(gta.get("story")),
        "render": clamp01(gta.get("render")),
        "perf": clamp01((_num(gta.get("fps")) or 0) / 30),
        "stability": stab,
    }


def js_round1(x: float) -> float:
    # Math.round(x * 10) / 10 do JavaScript (arredonda .5 para cima)
    return math.floor(x * 10 + 0.5) / 10


def score_effort(effort: dict) -> dict:
    gw = groundwork_fraction(effort.get("groundwork"))
    gta = effort.get("gta") or {}
    score = TICK["loads"] * gw
    reached = "groundwork"
    prev_tick = score

    for key in LADDER:
        v = ladder_value(gta.get(key))
        if v >= 1:
            score = TICK[key]
            prev_tick = score
            reached = key
            continue
        if v > 0:
            score = max(score, prev_tick + v * (TICK[key] - prev_tick))
        break

    tracks = track_values(gta)
    quality = sum(TRACK_WEIGHTS[k] * tracks[k] for k in TRACK_WEIGHTS)
    if reached == "playable":
        score = TICK["playable"] + quality * (TICK["complete"] - TICK["playable"])
        if quality >= 1:
            reached = "complete"

    manual = _num(effort.get("manualScore"))
    if manual is not None:
        score = min(100.0, max(0.0, manual))

    return {"score": js_round1(score), "reached": reached}


def is_private(effort: dict) -> bool:
    repo = effort.get("repo")
    return not (isinstance(repo, str) and "/" in repo)


def ranked_efforts(efforts: list[dict]) -> list[dict]:
    scored = []
    for e in efforts:
        if e.get("nuked"):
            continue
        scored.append({"effort": e, **score_effort(e)})
    scored.sort(key=lambda s: (-s["score"], -((s["effort"].get("stats") or {}).get("stars") or 0)))
    return scored


# --------------------------------------------------------------------------------------
# Rede / Telegram
# --------------------------------------------------------------------------------------


def http_get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_tracker() -> dict:
    # o proprio site usa ?ts=... para furar o cache
    return http_get_json(f"{DATA_URL}?ts={int(time.time())}")


def telegram_call(token: str, method: str, params: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Telegram {method} falhou ({e.code}): {body}") from None


def send_telegram(token: str, chat_id: str, text: str) -> None:
    telegram_call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    })


# --------------------------------------------------------------------------------------
# Mensagem
# --------------------------------------------------------------------------------------


def step_label(steps, v) -> str:
    v = clamp01(v)
    label = steps[0][1]
    for threshold, lab in steps:
        if v >= threshold:
            label = lab
    return label


def stability_label(v) -> str:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return STABILITY.get(v, STABILITY["unknown"])[0]
    best = "constant"
    for key, (_, val) in STABILITY.items():
        if key == "unknown":
            continue
        if abs(val - v) <= abs(STABILITY[best][1] - v) + 1e-9:
            best = key
    return STABILITY[best][0]


def fmt_pct(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".") + "%"


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def build_message(tracker: dict, ranked: list[dict], prev: dict | None, reason: str) -> str:
    lead = ranked[0]
    e = lead["effort"]
    gta = e.get("gta") or {}
    score = lead["score"]
    playable = lead["reached"] in ("playable", "complete")

    lines: list[str] = []

    # Cabecalho
    if prev is None:
        lines.append("🛰 <b>PortWatch VI: monitoramento iniciado</b>")
    elif reason == "test":
        lines.append("🧪 <b>PortWatch VI: status atual</b>")
    elif prev.get("leader_id") != e.get("id"):
        lines.append("👑 <b>PortWatch VI: NOVO LÍDER!</b>")
    else:
        diff = score - float(prev.get("score", 0))
        arrow = "📈" if diff > 0 else "📉"
        lines.append(f"{arrow} <b>PortWatch VI: a porcentagem do líder mudou</b>")
    lines.append("")

    # Porcentagem
    if prev is not None and reason != "test":
        old = float(prev.get("score", 0))
        diff = score - old
        sign = "+" if diff >= 0 else "−"
        old_name = prev.get("leader_name") or prev.get("leader_id")
        if prev.get("leader_id") != e.get("id"):
            lines.append(f"<b>{fmt_pct(old)}</b> ({esc(old_name)}) → <b>{fmt_pct(score)}</b> ({sign}{fmt_pct(abs(diff))})")
        else:
            lines.append(f"<b>{fmt_pct(old)} → {fmt_pct(score)}</b> ({sign}{fmt_pct(abs(diff))})")
    else:
        lines.append(f"<b>{fmt_pct(score)}</b>")

    # Projeto
    name = e.get("name") or e.get("id")
    repo = e.get("repo")
    if isinstance(repo, str) and "/" in repo:
        lines.append(f"🏆 <b>{esc(name)}</b> · <a href=\"https://github.com/{esc(repo)}\">{esc(repo)}</a>")
    else:
        lines.append(f"🏆 <b>{esc(name)}</b> · versão privada (sem código público)")
    meta = [MILESTONE_LABEL.get(lead["reached"], lead["reached"])]
    if e.get("approach"):
        meta.append(e["approach"])
    if e.get("target"):
        meta.append(e["target"])
    ver = {"portwatch": "Verificado pelo PortWatch", "self-reported": "Autodeclarado"}.get(e.get("verification"))
    if ver:
        meta.append(ver)
    lines.append("<i>" + esc(" · ".join(meta)) + "</i>")
    lines.append("")

    # Barras
    if playable:
        fps = _num(gta.get("fps"))
        lines.append(f"📖 História: {esc(step_label(STORY_STEPS, gta.get('story')))}")
        lines.append(f"🎨 Gráficos: {esc(step_label(RENDER_STEPS, gta.get('render')))}")
        lines.append(f"⚡ Desempenho: <b>{fmt_pct(fps).rstrip('%') if fps is not None else '?'} FPS</b>")
        lines.append(f"🧱 Estabilidade: {esc(stability_label(gta.get('stability')))}")
        lines.append("")

    if e.get("summary"):
        lines.append(esc(e["summary"]))
        lines.append("")

    if e.get("highlights"):
        lines.append("✅ <b>O que funciona</b>")
        lines.extend(f"• {esc(h)}" for h in e["highlights"])
        lines.append("")
    if e.get("blockers"):
        lines.append("❌ <b>O que está travando</b>")
        lines.extend(f"• {esc(b)}" for b in e["blockers"])
        lines.append("")

    proof = e.get("proof") or {}
    if proof.get("url"):
        lines.append(f"🎬 <a href=\"{esc(proof['url'])}\">{esc(proof.get('label') or 'Prova')}</a>")

    # Top 3
    lines.append("")
    lines.append("<b>Top 3</b>")
    for i, s in enumerate(ranked[:3], 1):
        ee = s["effort"]
        fps = _num((ee.get("gta") or {}).get("fps"))
        extra = f" · {fmt_pct(fps).rstrip('%')} FPS" if fps else ""
        priv = " (privada)" if is_private(ee) else ""
        lines.append(f"{i}. {esc(ee.get('name') or ee.get('id'))}{priv}: {fmt_pct(s['score'])}{extra}")

    updated = tracker.get("updated")
    lines.append("")
    lines.append(f"<a href=\"{BASE_URL}/#effort-{esc(e.get('id', ''))}\">Abrir no PortWatch</a>"
                 + (f" · dados de {esc(updated)}" if updated else ""))

    text = "\n".join(lines)
    if len(text) > 4000:  # limite do Telegram e 4096
        text = text[:3990] + "\n…"
    return text


# --------------------------------------------------------------------------------------
# Estado / config
# --------------------------------------------------------------------------------------


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_config() -> dict:
    cfg = load_json(CONFIG_FILE, None)
    if cfg is None:
        # No GitHub Actions nao existe config.json: os dados vem dos Secrets (variaveis de ambiente)
        import os
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            sys.exit(f"Arquivo {CONFIG_FILE.name} não encontrado. Copie config.example.json para config.json e preencha.")
        cfg = {
            "telegram_bot_token": token,
            "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
            "notify_on_fps_change": os.environ.get("NOTIFY_ON_FPS_CHANGE", "").lower() in ("1", "true", "yes"),
        }
    if not cfg.get("telegram_bot_token") or "COLE" in cfg.get("telegram_bot_token", ""):
        sys.exit("Preencha telegram_bot_token no config.json.")
    return cfg


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------------------
# Loop principal
# --------------------------------------------------------------------------------------


def check(cfg: dict | None, *, force: bool = False, dry_run: bool = False) -> None:
    tracker = fetch_tracker()
    ranked = ranked_efforts(tracker.get("efforts") or [])
    if not ranked:
        log("Nenhum projeto encontrado nos dados.")
        return

    lead = ranked[0]
    e = lead["effort"]
    current = {
        "leader_id": e.get("id"),
        "leader_name": e.get("name"),
        "score": lead["score"],
        "fps": (e.get("gta") or {}).get("fps"),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
    prev = load_json(STATE_FILE, None)

    changed = prev is None or prev.get("leader_id") != current["leader_id"] or float(prev.get("score", -1)) != current["score"]
    # opcional: tambem avisar quando so o FPS do lider muda
    if cfg and cfg.get("notify_on_fps_change") and prev and prev.get("leader_id") == current["leader_id"] \
            and prev.get("fps") != current["fps"]:
        changed = True

    log(f"Líder: {current['leader_name']} {fmt_pct(current['score'])}"
        + ("" if prev is None else f" (antes: {prev.get('leader_name')} {fmt_pct(float(prev.get('score', 0)))})"))

    if not (changed or force):
        return

    text = build_message(tracker, ranked, None if force else prev, "test" if force else "change")
    if dry_run:
        print("\n" + text + "\n")
    else:
        send_telegram(cfg["telegram_bot_token"], str(cfg["telegram_chat_id"]), text)
        log("Mensagem enviada no Telegram.")
    if not dry_run:
        save_json(STATE_FILE, current)


def get_chat_id(cfg: dict) -> None:
    res = telegram_call(cfg["telegram_bot_token"], "getUpdates")
    chats = {}
    for upd in res.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name")
    if not chats:
        print("Nenhuma conversa encontrada. Abra o seu bot no Telegram, mande /start e rode de novo.")
        return
    for cid, who in chats.items():
        print(f"chat_id: {cid}  ({who})")
    print("Cole o chat_id no config.json, em telegram_chat_id.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Avisa no Telegram quando a % do líder do PortWatch VI muda.")
    ap.add_argument("--once", action="store_true", help="checa uma vez e sai")
    ap.add_argument("--test", action="store_true", help="envia o status atual agora")
    ap.add_argument("--dry-run", action="store_true", help="só imprime a mensagem, não envia")
    ap.add_argument("--get-chat-id", action="store_true", help="descobre o seu chat_id")
    args = ap.parse_args()

    if args.dry_run:
        check(None, force=True, dry_run=True)
        return

    cfg = load_config()
    if args.get_chat_id:
        get_chat_id(cfg)
        return
    if not cfg.get("telegram_chat_id"):
        sys.exit("Preencha telegram_chat_id no config.json (use --get-chat-id para descobrir).")

    if args.test:
        check(cfg, force=True)
        return
    if args.once:
        check(cfg)
        return

    interval = max(60, int(cfg.get("interval_seconds", 300)))
    log(f"Monitorando {BASE_URL} a cada {interval}s. Ctrl+C para parar.")
    while True:
        try:
            check(cfg)
        except Exception as exc:  # rede caiu, site fora do ar etc.: tenta de novo no proximo ciclo
            log(f"Erro: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
