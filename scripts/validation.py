#!/usr/bin/env python3
"""Le Lobby — validation Telegram et publication, SANS Claude (lancé par GitHub Actions).

  validation.py envoyer                 -> envoie à Alix les vidéos « à valider » pas encore envoyées
  validation.py decider <num> <action> [valeur]
        actions : ok | non (valeur = raison) | titre (valeur = nouveau titre) | annuler
  validation.py publier [--essai] [--confirmer]
                                        -> au créneau : publie la vidéo validée la mieux notée encore fraîche

Secrets (variables d'environnement) : TELEGRAM_BOT_TOKEN, ZERNIO_API_KEY.
L'identifiant du chat d'Alix est demandé au Worker Cloudflare (adresse : state/worker.json), jamais écrit dans le dépôt.
Statuts et journal : state/published.json (voir scripts/lobby.py).
"""
import datetime as dt, hashlib, json, os, re, subprocess, sys, tempfile, time, uuid
import urllib.error, urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lobby as L

TAIPEI = ZoneInfo("Asia/Taipei")
TG_API = os.environ.get("TELEGRAM_API", "https://api.telegram.org")
ZR_API = os.environ.get("ZERNIO_API", "https://zernio.com/api/v1")
RAW = os.environ.get("LOBBY_RAW", "https://raw.githubusercontent.com/lelobbyactu/medias/main")


# ---------- HTTP ----------
def http(method, url, data=None, headers=None, timeout=300):
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "lelobby", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, code = e.read(), e.code
    try: return code, json.loads(body or b"{}")
    except ValueError: return code, {"raw": body[:300].decode("utf-8", "replace")}


# ---------- Telegram ----------
def token(): return os.environ["TELEGRAM_BOT_TOKEN"]

def chat_id():
    if os.environ.get("TELEGRAM_CHAT_ID"): return os.environ["TELEGRAM_CHAT_ID"]
    url = (L.load(f"{L.ROOT}/state/worker.json") or {}).get("url")
    if not url: return None
    key = hashlib.sha256(f"{token()}:api".encode()).hexdigest()
    code, j = http("GET", f"{url}/chat", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    cid = j.get("chat_id") if code == 200 else None
    if cid and os.environ.get("GITHUB_ACTIONS"): print(f"::add-mask::{cid}")   # journaux publics : jamais affiché
    return cid

def multipart(fields, files):
    b = uuid.uuid4().hex; out = []
    for k, v in fields.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (name, content, mime) in files.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode() + content + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"

def tg(method, fields, files=None):
    url = f"{TG_API}/bot{token()}/{method}"
    if files:
        data, ct = multipart(fields, files)
    else:
        data, ct = json.dumps(fields).encode(), "application/json"
    code, j = http("POST", url, data, {"Content-Type": ct})
    if code != 200 or not j.get("ok"): raise RuntimeError(f"Telegram {method} : {code} {j.get('description', '')}")
    return j["result"]

def say(text):
    cid = chat_id()
    if not cid: return
    try: tg("sendMessage", {"chat_id": cid, "text": text[:4000], "disable_web_page_preview": True})
    except Exception as e: print("message non envoyé :", e)

def clear_buttons(x):
    cid = chat_id(); mid = x.get("telegram_msg")
    if cid and mid:
        try: tg("editMessageReplyMarkup", {"chat_id": cid, "message_id": mid, "reply_markup": {"inline_keyboard": []}})
        except Exception: pass


# ---------- utilitaires ----------
def num(x): return x["id"][:4]
def plat_list(x):
    """Instagram toujours ; TikTok sauf 16:9, sponsor, ou pause."""
    c = L.cfg(); today = L.now().astimezone(L.PARIS).date().isoformat()
    ok = x.get("format") == "9:16" and x.get("garde_fou") == "OK" and today > (c.get("tiktok_pause_until") or "")
    return ["instagram", "tiktok"] if ok else ["instagram"]
def score(x):
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)", str(x.get("judge_score", "0")))
    return float(m.group(1).replace(",", ".")) if m else 0.0
def hm(s, z=TAIPEI): return L.parse(s).astimezone(z).strftime("%d/%m %H:%M")
def update(pid, fields, msg, expect=None):
    """Modifie un post du journal ; `expect` = statuts attendus (sinon rien, renvoie None)."""
    def apply():
        p = L.pload(); x = next(i for i in p["posts"] if i["id"] == pid)
        if expect and x["status"] not in expect: return None
        for k, v in fields.items():
            if v is None: x.pop(k, None)
            else: x[k] = v
        L.save(L.P, p); return dict(x)
    return L.transact(apply, msg, "state")
def raw_url(pid, suffix): return f"{RAW}/posts/{pid}/{pid}{suffix}"


# ---------- Zernio ----------
def zr(method, path, body=None, headers=None):
    h = {"Authorization": f"Bearer {os.environ['ZERNIO_API_KEY']}", "Content-Type": "application/json", **(headers or {})}
    return http(method, f"{ZR_API}{path}", json.dumps(body).encode() if body is not None else None, h)

def zr_body(x, quand=None):
    c = L.cfg(); acc = c["zernio_accounts"]; plats = plat_list(x)
    entries = []
    for pf in plats:
        e = {"platform": pf, "accountId": acc[pf]}
        if pf == "instagram": e["platformSpecificData"] = {"contentType": "reels", "instagramThumbnail": raw_url(x["id"], "_cover.jpg")}
        entries.append(e)
    body = {"content": x["legende"], "platforms": entries,
            "mediaItems": [{"type": "video", "url": raw_url(x["id"], ".mp4")}]}
    if "tiktok" in plats:
        body["tiktokSettings"] = {"privacy_level": "PUBLIC_TO_EVERYONE", "allow_comment": True, "allow_duet": True,
                                  "allow_stitch": True,
                                  "content_preview_confirmed": True, "express_consent_given": True}
    if quand: body.update({"scheduledFor": quand})
    else: body["publishNow"] = True
    return body

def zr_create(x, quand=None):
    if not os.environ.get("LOBBY_NOCHECK"):
        for _ in range(6):   # le fichier doit être en ligne avant que Zernio le télécharge
            code = subprocess.run(["curl", "-s", "-I", "-o", "/dev/null", "-w", "%{http_code}", raw_url(x["id"], ".mp4")],
                                  capture_output=True, text=True).stdout.strip()
            if code == "200": break
            time.sleep(10)
        else: return 0, {"error": f"vidéo introuvable en ligne ({code})"}
    key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"lelobby/{x['id']}/{x.get('titre')}/{quand or 'now'}"))
    return zr("POST", "/posts", zr_body(x, quand), {"Idempotency-Key": key})

def zr_result(post):
    """(liens publiés par plateforme, erreurs)."""
    ok, ko = {}, []
    for pf in post.get("platforms", []):
        if pf.get("platformPostUrl"): ok[pf["platform"]] = pf["platformPostUrl"]
        elif pf.get("status") == "failed" or pf.get("errorMessage"): ko.append(f"{pf.get('platform')} : {pf.get('errorMessage') or 'échec'}")
    return ok, ko


# ---------- envoyer ----------
def legende_message(x):
    c = L.cfg(); titre = x["titre"].replace("|", " ").replace("*", "")
    tete = (f"🚨 URGENT · #{num(x)}\nPart dans {c.get('urgent_delay_min', 20)} min si tu n'annules pas."
            if x.get("urgent") else f"🎬 #{num(x)} · à valider avant le {hm(x['expires_at_utc'])} (Taipei)")
    reseaux = " + ".join("Instagram" if p == "instagram" else "TikTok" for p in plat_list(x))
    txt = f"{tete}\n\n{titre}\nJuge : {x['judge_score']} · {x['format']} · {reseaux}\n\n{x['legende']}"
    return txt[:1024]

def clavier(x):
    n = num(x)
    if x.get("urgent"): return [[{"text": "✋ Annuler", "callback_data": f"annuler:{n}"}]]
    ligne = [{"text": "✅ Poster", "callback_data": f"ok:{n}"}, {"text": "❌ Non", "callback_data": f"non:{n}"}]
    rows = [ligne]
    meta = L.load(f"{L.ROOT}/posts/{x['id']}/{x['id']}_montage.json") or {}
    extra = [{"text": "✏️ Autre titre", "callback_data": f"alt:{n}"}] if meta.get("bande") else []
    extra.append({"text": "🔧 Retoucher", "callback_data": f"retoucher:{n}"})
    rows.append(extra)
    return rows

def sparse_add(pid):
    if os.environ.get("GITHUB_ACTIONS") and not os.path.isdir(f"{L.ROOT}/posts/{pid}"):
        L.sh(f"git sparse-checkout add 'posts/{pid}'")

def envoyer():
    L.sync()
    todo = [x for x in L.pload()["posts"] if x["status"] == "a_valider" and not x.get("telegram_msg")]
    if not todo: return print("rien à envoyer")
    cid = chat_id()
    if not cid: return print("bot pas encore relié (déployer le Worker puis envoyer /start au bot)")
    for item in sorted(todo, key=lambda x: (not x.get("urgent"), -score(x))):
        pid = item["id"]
        def claim():
            p = L.pload(); x = next(i for i in p["posts"] if i["id"] == pid); old = L.parse(x.get("envoi_utc"))
            if x["status"] != "a_valider" or x.get("telegram_msg") or (old and (L.now() - old).total_seconds() < 600): return None
            x["envoi_utc"] = L.iso(L.now()); L.save(L.P, p); return dict(x)
        x = L.transact(claim, f"validation: envoi {pid}", "state")
        if not x: continue
        if L.parse(x["expires_at_utc"]) < L.now():
            update(pid, {"status": "expire"}, f"validation: {pid} expiré avant envoi"); continue
        try:
            sparse_add(pid)
            with open(f"{L.ROOT}/posts/{pid}/{pid}.mp4", "rb") as f: video = f.read()
            if len(video) > 49_500_000: raise RuntimeError(f"vidéo de {len(video) / 1e6:.0f} Mo (limite Telegram 50 Mo)")
            r = tg("sendVideo", {"chat_id": cid, "caption": legende_message(x), "width": 1080, "height": 1920,
                                 "supports_streaming": "true", "reply_markup": json.dumps({"inline_keyboard": clavier(x)})},
                   {"video": (f"{pid}.mp4", video, "video/mp4")})
        except Exception as e:
            say(f"⚠️ #{pid[:4]} : envoi de la vidéo impossible ({e})")
            update(pid, {"status": "echec", "note": str(e)[:200]}, f"validation: échec envoi {pid}"); continue
        champs = {"telegram_msg": r["message_id"], "envoi_utc": None}
        if x.get("urgent"):   # option A : programmée à +20 min, annulable
            quand = L.iso(L.now() + dt.timedelta(minutes=L.cfg().get("urgent_delay_min", 20)))
            code, j = zr_create(x, quand)
            if code in (200, 201):
                champs.update({"status": "programme", "published_at_utc": quand, "zernio_post_id": j["post"]["_id"]})
            else:
                say(f"⚠️ #{num(x)} : programmation Zernio refusée ({code}). Rien ne partira.")
                champs.update({"status": "echec", "note": f"zernio {code} {str(j)[:150]}"})
        update(pid, champs, f"validation: envoyé {pid}")
        print("envoyé", pid)


# ---------- décider ----------
def find(n):
    for x in reversed(L.pload()["posts"]):
        if x["id"].startswith(f"{n}-"): return x
    raise SystemExit(f"post #{n} introuvable")

def mise_en_forme(t):
    """Titre tapé par Alix : « | » = retour à la ligne ; sinon lignes d'environ 14 caractères."""
    t = " ".join(t.split())
    if "|" in t: return t
    lignes, cur = [], ""
    for w in t.split(" "):
        if cur and len((cur + " " + w).replace("*", "")) > 16 and cur.count("*") % 2 == 0: lignes.append(cur); cur = w
        else: cur = f"{cur} {w}".strip()
    return "|".join(lignes + [cur])

def retitrer(x, titre):
    """Remplace la bande titre sur la vidéo déjà montée (son et sous-titres inchangés)."""
    import make_reel as R
    pid = x["id"]; sparse_add(pid); d = f"{L.ROOT}/posts/{pid}"
    meta = L.load(f"{d}/{pid}_montage.json") or {}
    if not meta.get("bande"): raise RuntimeError("titre non remplaçable sur cette mise en page")
    y0, y1 = meta["bande"]; h = y1 - y0
    th, _ = R.title_html(titre)
    css = "".join([R.font_face("Unbounded", "unbounded-latin-800-normal.woff2", 800)])
    doc = f"""<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:transparent;overflow:hidden}}
.box{{position:absolute;left:0;top:{y0}px;width:1080px;height:{h}px;background:{R.BG};display:flex;flex-direction:column;justify-content:center}}
.title{{text-align:center;color:#fff;font-family:Unbounded;font-weight:800;text-transform:uppercase;font-size:64px;line-height:1.14;letter-spacing:-.5px}}
.ln{{white-space:nowrap;display:block;width:max-content;margin:0 auto}}
.hl{{background:{R.Y};color:{R.BG};padding:0 .14em}}
</style></head><body><div class='box'><div class='title' id='t'>{th}</div></div></body></html>"""
    from playwright.sync_api import sync_playwright
    import pathlib
    tmp = pathlib.Path(tempfile.mkdtemp()); page = tmp / "t.html"; png = tmp / "t.png"; page.write_text(doc, encoding="utf-8")
    with sync_playwright() as p:
        kw = {"args": ["--allow-file-access-from-files", "--no-sandbox"]}
        if os.path.exists("/usr/bin/google-chrome"): kw["executable_path"] = "/usr/bin/google-chrome"
        b = p.chromium.launch(**kw); pg = b.new_page(viewport={"width": 1080, "height": 1920})
        pg.goto(page.as_uri()); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(400)
        pg.evaluate(f"""() => {{ const t = document.getElementById('t'); let fs = 64;
          const W = () => Math.max(...[...t.querySelectorAll('.ln')].map(e => e.getBoundingClientRect().width));
          while ((W() > 980 || t.getBoundingClientRect().height > {h - 12}) && fs > 30) {{ fs -= 2; t.style.fontSize = fs + 'px'; }} }}""")
        pg.wait_for_timeout(100); pg.screenshot(path=str(png), omit_background=True); b.close()
    src = f"{d}/{pid}.mp4"; new = str(tmp / "v.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-i", str(png), "-filter_complex",
                    "[0:v][1:v]overlay=0:0,format=yuv420p[o]", "-map", "[o]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast",
                    "-crf", "19", "-profile:v", "high", "-c:a", "copy", "-movflags", "+faststart", new], check=True)
    cover = str(tmp / "c.jpg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5", "-i", new, "-frames:v", "1", "-q:v", "3", cover], check=True)
    return new, cover

def decider(n, action, valeur=""):
    L.sync(); x = find(n); pid = x["id"]; st = x["status"]
    if action == "ok":
        if not update(pid, {"status": "valide", "validated_at_utc": L.iso(L.now())}, f"validation: {pid} validé", ("a_valider",)):
            return say(f"#{n} : déjà traité ({st}).")
        clear_buttons(x)
        say(f"✅ #{n} validé. Il partira à un créneau selon sa note ({x['judge_score']}), avant le {hm(x['expires_at_utc'])} (Taipei).")
    elif action in ("non", "annuler"):
        if st == "programme":
            code, j = zr("DELETE", f"/posts/{x['zernio_post_id']}")
            if code not in (200, 204): return say(f"⚠️ #{n} : annulation refusée par Zernio ({code}). Il est peut-être déjà parti.")
        raison = (valeur or ("annulé" if action == "annuler" else "sans raison")).strip()[:120]
        if not update(pid, {"status": "refuse", "refus": raison}, f"validation: {pid} refusé", ("a_valider", "valide", "programme")):
            return say(f"#{n} : trop tard, déjà {st}.")
        def note():
            f = f"{L.ROOT}/juge/refus.md"
            head = "# Refus d'Alix (le juge lit les 15 premiers avant chaque notation)\n\n"
            old = open(f, encoding="utf-8").read() if os.path.exists(f) else head
            ligne = (f"- {L.now().astimezone(L.PARIS):%d/%m} · **{raison}** · titre « {x.get('titre', '').replace('|', ' ')} » · "
                     f"{x.get('topic', '')} · juge {x.get('judge_score')}\n")
            body = old[len(head):] if old.startswith(head) else old
            os.makedirs(os.path.dirname(f), exist_ok=True)
            open(f, "w", encoding="utf-8").write(head + ligne + "".join(body.splitlines(True)[:99]))
        L.transact(note, f"juge: refus {pid}", "state juge")
        clear_buttons(x); say(f"🗑️ #{n} écarté ({raison}).")
    elif action == "titre":
        if st != "a_valider": return say(f"#{n} : titre non modifiable ({st}).")
        titre = mise_en_forme(valeur)
        if not titre: return say(f"#{n} : titre vide.")
        try: new, cover = retitrer(x, titre)
        except Exception as e:
            restore_buttons(x); return say(f"⚠️ #{n} : impossible de changer le titre ({e}).")
        alts = [t for t in [x["titre"]] + x.get("titres_alt", []) if t != titre][:2]
        def apply():
            p = L.pload(); y = next(i for i in p["posts"] if i["id"] == pid)
            if y["status"] != "a_valider": return None
            import shutil
            shutil.copy(new, f"{L.ROOT}/posts/{pid}/{pid}.mp4"); shutil.copy(cover, f"{L.ROOT}/posts/{pid}/{pid}_cover.jpg")
            y.update({"titre": titre, "titres_alt": alts}); y.pop("telegram_msg", None); y.pop("envoi_utc", None)
            L.save(L.P, p); return True
        if L.transact(apply, f"validation: nouveau titre {pid}", f"state posts/{pid}"):
            clear_buttons(x); time.sleep(0 if os.environ.get("LOBBY_NOCHECK") else 20); envoyer()
    elif action == "retouche":
        if st != "a_valider": return say(f"#{n} : retouche impossible ({st}).")
        appliquer_retouche(n, x, valeur)
    elif action == "autre":
        if not update(pid, {"status": "retouche", "demande": valeur.strip()[:300]}, f"validation: retouche demandée {pid}", ("a_valider",)):
            return say(f"#{n} : retouche impossible ({st}).")
        clear_buttons(x)
        say(f"🛠️ #{n} : demande notée. Elle sera faite à la prochaine session de production, avant expiration ({hm(x['expires_at_utc'])}, Taipei).")
    else: raise SystemExit(f"action inconnue : {action}")


# ---------- retoucher ----------
CHOIX = {"cam": "webcam moins zoomée", "jeu": "gameplay moins zoomé", "deux": "webcam et gameplay moins zoomés",
         "16x9": "format 16:9", "debut": "début raccourci de 2 s", "fin": "fin raccourcie de 2 s"}

def restore_buttons(x):
    """Échec d'un changement : on remet les boutons sous la vidéo."""
    cid = chat_id(); mid = x.get("telegram_msg")
    if cid and mid:
        try: tg("editMessageReplyMarkup", {"chat_id": cid, "message_id": mid, "reply_markup": {"inline_keyboard": clavier(x)}})
        except Exception: pass

def retoucher(x, choix):
    """Remonte la vidéo depuis sa source avec le réglage demandé (mêmes titre et sous-titres)."""
    pid = x["id"]; sparse_add(pid); d = f"{L.ROOT}/posts/{pid}"; clip = x.get("clip") or {}
    meta = L.load(f"{d}/{pid}_montage.json") or {}
    if not clip.get("url") or "start" not in meta: raise RuntimeError("source du montage non conservée")
    if choix in ("cam", "jeu", "deux"):
        if meta["format"] != "9:16": raise RuntimeError("le dézoom ne concerne que le format vertical")
        if choix == "cam" and not meta.get("cam"): raise RuntimeError("cette vidéo n'a pas de webcam")
    tmp = tempfile.mkdtemp(); src = f"{tmp}/source.mp4"; out = f"{tmp}/out"; os.makedirs(out)
    L.fetch_media(clip["url"], src, clip.get("offset") or 0, clip.get("dur"))
    start, end = meta["start"], meta["end"]
    subs = L.load(f"{d}/{pid}_soustitres.json") if os.path.exists(f"{d}/{pid}_soustitres.json") else None
    if choix in ("debut", "fin"):
        if end - start - 2 < 6: raise RuntimeError("vidéo déjà très courte")
        if choix == "debut":
            start += 2
            if subs is not None: subs = [{**w, "debut": w["debut"] - 2, "fin": w["fin"] - 2} for w in subs if w["debut"] >= 2]
        else:
            end -= 2
            if subs is not None: subs = [w for w in subs if w["debut"] < end - start]
    vertical = meta["format"] == "9:16" and choix != "16x9"
    cmd = [sys.executable, f"{L.ROOT}/scripts/{'make_reel_916' if vertical else 'make_reel'}.py", "--video", src, "--post", pid,
           "--title", x["titre"], "--start", f"{start:.2f}", "--end", f"{end:.2f}", "--out-dir", out]
    if subs:
        L.save(f"{out}/{pid}_soustitres.json", subs); cmd += ["--subs-json", f"{out}/{pid}_soustitres.json"]
    else: cmd += ["--no-subs"]
    if vertical:
        ref = f"{tmp}/ref.json"; L.save(ref, meta); cmd += ["--refaire", ref]
        if meta.get("channel"): cmd += ["--channel", meta["channel"]]
        if choix in ("cam", "deux"): cmd += ["--dezoom-cam"]
        if choix in ("jeu", "deux"): cmd += ["--dezoom-jeu"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode or not os.path.exists(f"{out}/{pid}.mp4"):
        raise RuntimeError(f"montage refusé : {(r.stdout or r.stderr).strip()[-250:]}")
    return out

def appliquer_retouche(n, x, choix):
    pid = x["id"]
    if choix not in CHOIX: return say(f"#{n} : retouche inconnue.")
    try: out = retoucher(x, choix)
    except Exception as e:
        restore_buttons(x); return say(f"⚠️ #{n} : retouche impossible ({e}).")
    def apply():
        import shutil
        p = L.pload(); y = next(i for i in p["posts"] if i["id"] == pid)
        if y["status"] != "a_valider": return None
        for f in os.listdir(out):
            if f.startswith(pid) and not f.endswith(".html"): shutil.copy(f"{out}/{f}", f"{L.ROOT}/posts/{pid}/{f}")
        y["format"] = L.load(f"{L.ROOT}/posts/{pid}/{pid}_montage.json")["format"]
        if choix in ("jeu", "cam", "deux") and y.get("garde_fou") == "OK":
            y["garde_fou"] = "SPONSOR"   # zones d'image non contrôlées par le garde-fou : Instagram seul
        y.setdefault("retouches", []).append(choix); y.pop("telegram_msg", None); y.pop("envoi_utc", None)
        L.save(L.P, p); return True
    if L.transact(apply, f"validation: retouche {choix} {pid}", f"state posts/{pid}"):
        clear_buttons(x); time.sleep(0 if os.environ.get("LOBBY_NOCHECK") else 20); envoyer()

# ---------- publier ----------
def publier(essai=False, confirmer=False):
    L.sync(); t = L.now()
    # 1. urgences programmées et publications interrompues : on relit l'état chez Zernio
    for x in [x for x in L.pload()["posts"] if x["status"] in ("programme", "publication")]:
        if L.parse(x["published_at_utc"]) > t - dt.timedelta(minutes=3) or essai: continue
        if x.get("zernio_post_id"): code, j = zr("GET", f"/posts/{x['zernio_post_id']}"); post = j.get("post") or {}
        else:   # réponse perdue : on retrouve le post par sa vidéo ou sa description
            code, j = zr("GET", "/posts?limit=50")
            post = next((p for p in j.get("posts", []) if p.get("content") == x["legende"]
                         or any(f"/{x['id']}/" in (m.get("url") or "") for m in p.get("mediaItems", []))), {})
        if code != 200: continue
        ok, ko = zr_result(post)
        if ok:
            update(x["id"], {"status": "publie", "zernio_post_id": post.get("_id"), **ok}, f"journal: publié {x['id']}")
            say(f"🚀 #{num(x)} en ligne\n" + "\n".join(ok.values()) + ("\n⚠️ " + " ; ".join(ko) if ko else ""))
        elif post.get("status") in ("failed", "cancelled") or not post:
            update(x["id"], {"status": "echec", "note": "; ".join(ko)[:200] or "absent chez Zernio"}, f"journal: échec {x['id']}")
            say(f"⚠️ #{num(x)} : publication en échec. {' ; '.join(ko)}")
    # 2. expirations
    for x in [x for x in L.pload()["posts"] if x["status"] in ("a_valider", "valide", "retouche")]:
        if L.parse(x["expires_at_utc"]) < t and not essai:
            update(x["id"], {"status": "expire"}, f"validation: {x['id']} expiré", ("a_valider", "valide", "retouche"))
            clear_buttons(x); say(f"⌛ #{num(x)} expiré ({'validé mais pas de créneau libre' if x['status'] == 'valide' else 'pas de réponse'}).")
    # 3. un post par créneau
    if confirmer: return print("passage de contrôle : rien à publier")
    c = L.cfg(); posts = L.pload()["posts"]; n, last = L.today_stats(posts)
    valides = sorted([x for x in posts if x["status"] == "valide" and L.parse(x["expires_at_utc"]) > t],
                     key=lambda x: (-score(x), x["expires_at_utc"]))
    if not valides: return print("aucune vidéo validée")
    if n >= c["cap_per_day"]: return print("plafond du jour atteint")
    if last and abs((t - last).total_seconds()) < c["min_gap_min"] * 60: return print("post trop récent ou programmé bientôt")
    x = valides[0]
    if essai: return print("essai :", x["id"], json.dumps(zr_body(x), ensure_ascii=False))
    x = update(x["id"], {"status": "publication", "published_at_utc": L.iso(t)}, f"journal: publication {x['id']}", ("valide",))
    if not x: return
    code, j = zr_create(x); post = j.get("post") or {}; ok, ko = zr_result(post)
    if ok:
        update(x["id"], {"status": "publie", "zernio_post_id": post.get("_id"), "published_at_utc": L.iso(L.now()), **ok},
               f"journal: publié {x['id']}")
        say(f"🚀 #{num(x)} en ligne\n" + "\n".join(ok.values()) + ("\n⚠️ " + " ; ".join(ko) if ko else ""))
    elif code in (0, 400, 401, 402, 403, 404, 422) or post.get("status") == "failed":
        update(x["id"], {"status": "echec", "note": f"zernio {code} {str(j)[:150]}"}, f"journal: échec {x['id']}")
        say(f"⚠️ #{num(x)} : publication refusée ({code}). {' ; '.join(ko) or str(j.get('error', ''))[:200]}")
    else:   # en cours chez Zernio ou réponse incertaine : relu au prochain passage
        if post.get("_id"): update(x["id"], {"zernio_post_id": post["_id"]}, f"journal: en cours {x['id']}")
        print("publication en cours ou incertaine :", code)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: raise SystemExit(__doc__)
    if a[0] == "envoyer": envoyer()
    elif a[0] == "decider" and len(a) >= 3:
        if not re.fullmatch(r"\d{4}", a[1]): raise SystemExit("numéro invalide")
        decider(a[1], a[2], a[3] if len(a) > 3 else "")
    elif a[0] == "publier": publier("--essai" in a, "--confirmer" in a)
    else: raise SystemExit(__doc__)
