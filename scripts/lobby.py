#!/usr/bin/env python3
"""Le Lobby : plomberie du pipeline (file d'attente, journal, ménage, git).
Les tâches Claude ne font plus ces calculs à la main : elles appellent ces commandes.

  lobby.py queries              -> requêtes Apify prêtes (fenêtre depuis la dernière veille)
  lobby.py sources [-n 20]      -> clips hors X (Twitch, Reddit) apparus depuis la
                                   dernière veille (state/sources.json, collecté par GitHub Actions) ; à lancer AVANT `add`
  lobby.py add [fichier.json]   -> ajoute/fusionne des sujets dans la file (stdin si pas de fichier), ménage, commit, push
  lobby.py lot                  -> session de production : 4 vidéos max, meilleurs candidats encore frais
  lobby.py proposer <post> <fiche.json> [--urgent] -> envoi en validation Telegram, sujet retiré de la file
  lobby.py slot [--hot]         -> contrôles (réseau, plafond, 45 min) + 3 meilleurs candidats (JSON court)
  lobby.py take <id>            -> passe le sujet en 'pris' + télécharge le clip dans /tmp/clip.mp4
                                   (+ remplace par la version Twitch 1080p60 si trouvée, champ "twitch" ; --no-twitch pour l'éviter)
  lobby.py reserve <id> reel Clips  -> réserve le numéro de post, journal 'en_cours'
  lobby.py done <post> [--ig U --tiktok U --zernio ID --judge 8/10 --slot 12h | --hot drama --note T]
  lobby.py fail <post> <raison>  | lobby.py drop <id> <raison>
  lobby.py push "<message>" <chemins...>  -> commit + push de fichiers (posts/…)
  lobby.py status               -> compte rapide
Variable LOBBY_NOPUSH=1 : n'écrit que localement (tests).
"""
import argparse, datetime as dt, json, os, re, subprocess, sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q, P, M, C = (f"{ROOT}/state/queue.json", f"{ROOT}/state/published.json",
              f"{ROOT}/state/meta.json", f"{ROOT}/config.json")
PARIS = ZoneInfo("Europe/Paris")
NOPUSH = bool(os.environ.get("LOBBY_NOPUSH"))
CLOSED = ("publie", "expire", "ecarte")
# statuts d'un post du journal : en_cours (montage) → a_valider (envoyé à Alix) → valide → publication → publie
# (ou programme : drama urgent daté par Zernio) ; fins possibles : refuse, expire, echec
PRIS = ("en_cours", "retouche", "a_valider", "valide", "publication", "programme", "publie", "refuse", "expire")  # sujet déjà traité
PARTI = ("publication", "programme", "publie")   # compte dans le plafond du jour et l'espacement


# ---------- utilitaires ----------
def now(): return dt.datetime.now(dt.timezone.utc)
def iso(d): return d.strftime("%Y-%m-%dT%H:%M:%SZ")
def parse(s):
    if not s: return None
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except FileNotFoundError: return default
def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1); f.write("\n")
def out(obj): print(json.dumps(obj, ensure_ascii=False, indent=1))
def cfg(): return load(C, {})
def sh(cmd, check=True):
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode: raise RuntimeError(f"{cmd}\n{r.stdout}{r.stderr}")
    return r

def network_ok():
    r = sh('curl -s -m 15 -o /dev/null -w "%{http_code}" https://video.twimg.com/', check=False)
    return r.stdout.strip() == "400"


# ---------- git ----------
GIT = 'git -c user.name="Le Lobby bot" -c user.email="lelobbyactu@gmail.com"'
def sync():
    if NOPUSH: return
    sh("git fetch -q --depth 1 origin main"); sh("git reset -q --mixed origin/main")
    sh("git checkout -q origin/main -- state")
def commit_push(msg, paths):
    if NOPUSH: return True
    sh(f"git add -A -- {paths}")
    if not sh("git diff --cached --quiet", check=False).returncode: return True
    sh(f'{GIT} commit -q -m "{msg}"')
    if NOPUSH: return True
    return sh("git push -q origin HEAD:main", check=False).returncode == 0
def transact(fn, msg, paths="state queue"):
    """Rejoue fn sur l'état distant frais jusqu'à ce que le push passe (4 essais)."""
    for _ in range(4):
        sync()
        res = fn()
        if commit_push(msg, paths): return res
    raise RuntimeError("push impossible après 4 essais")
def push_paths(msg, paths):
    for _ in range(4):
        sync()
        if commit_push(msg, paths): return True
    raise RuntimeError("push impossible après 4 essais")


# ---------- état ----------
def qload():
    q = load(Q, {"_doc": "", "candidates": []}); return q
def pload(): return load(P, {"_doc": "", "posts": []})
def post_time(p): return parse(p.get("published_at_utc") or p.get("reserved_at_utc"))

def today_stats(posts):
    mid = now().astimezone(PARIS).replace(hour=0, minute=0, second=0, microsecond=0)
    live = [p for p in posts if p.get("status") in PARTI and post_time(p) and post_time(p) >= mid]
    last = max((post_time(p) for p in live), default=None)
    return len(live), last

def ménage(q, p):
    t = now(); n_exp = n_del = 0
    for e in q["candidates"]:
        st = e.get("status")
        if st == "en_attente" and parse(e.get("expires_at_utc")) and parse(e["expires_at_utc"]) < t:
            e["status"] = "expire"; e["closed_at_utc"] = iso(t); n_exp += 1
        elif st == "pris" and (t - parse(e.get("taken_at_utc") or e["added_at_utc"])).total_seconds() > 90 * 60:
            e["status"] = "en_attente"
    keep = []
    for e in q["candidates"]:
        if e.get("status") in CLOSED:
            ref = parse(e.get("closed_at_utc") or e.get("expires_at_utc") or e.get("added_at_utc"))
            if ref and (t - ref).total_seconds() > 48 * 3600:
                mp = e.get("media_repo_path")
                if mp and os.path.exists(f"{ROOT}/{mp}"): os.remove(f"{ROOT}/{mp}")
                n_del += 1; continue
        keep.append(e)
    q["candidates"] = keep[-300:]
    # mp4 montés des vieux posts (>3 j) : inutiles une fois publiés (les covers restent)
    for post in p["posts"]:
        pt = post_time(post)
        age_max = {"publie": 3, "refuse": 1, "expire": 1}.get(post.get("status"))
        if age_max and pt and (t - pt).days >= age_max:
            d = f"{ROOT}/posts/{post['id']}"
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.endswith((".mp4", "_fond.png")): os.remove(f"{d}/{f}")
    p["posts"] = p["posts"][-200:]
    return n_exp, n_del

def covered(e, posts):
    for x in posts:
        if x.get("status") in PRIS:
            if e.get("topic_key") and e["topic_key"] == x.get("topic_key"): return True
            if e.get("source_tweet") and e["source_tweet"] == x.get("source_tweet"): return True
            if e.get("id") and e["id"] == x.get("queue_id"): return True
    return False


# ---------- commandes ----------
def cmd_queries(a):
    c = cfg(); m = load(M, {}); t = now()
    last = parse(m.get("last_veille_utc"))
    start = max(t - dt.timedelta(hours=6), (last - dt.timedelta(minutes=5)) if last else t - dt.timedelta(hours=2, minutes=15))
    since = start.strftime("%Y-%m-%d_%H:%M:%S_UTC")
    qs = [f"({' OR '.join('from:' + x for x in g)}) since:{since} -filter:retweets" for g in c["query_groups"]]
    out({"debut_utc": since, "maxItems": c.get("apify_max_items", 300), "searchTerms": qs})

def cmd_sources(a):
    sys.path.insert(0, f"{ROOT}/scripts"); import sources as S
    m = load(M, {}); last = parse(m.get("last_veille_utc"))
    since = (last - dt.timedelta(minutes=5)) if last else now() - dt.timedelta(hours=2, minutes=15)
    data = load(f"{ROOT}/state/sources.json", {"items": []})
    res = S.brief(data["items"], since, a.n)
    upd = parse(data.get("updated_utc"))
    res["collecte"] = {"derniere_utc": data.get("updated_utc"), "retard_min": int((now() - upd).total_seconds() / 60) if upd else None,
                       "rapport": {k: v for k, v in (data.get("report") or {}).items() if "erreur" in str(v) or "ignoré" in str(v)}}
    out(res)

def cmd_add(a):
    raw = open(a.file, encoding="utf-8").read() if a.file else sys.stdin.read()
    items = json.loads(raw) if raw.strip() else []
    if isinstance(items, dict): items = [items]
    c = cfg(); res = {"ajoutes": [], "fusionnes": [], "ignores": [], "hot": []}

    def apply():
        res.update({"ajoutes": [], "fusionnes": [], "ignores": [], "hot": []})
        q, p = qload(), pload(); t = now()
        n_exp, n_del = ménage(q, p)
        for it in items:
            if not it.get("source_tweet") and it.get("source_url"): it["source_tweet"] = it["source_url"]
            if not all(it.get(k) for k in ("type", "topic", "topic_key", "origin", "source_tweet", "source_time_utc", "score")):
                res["ignores"].append((it.get("topic_key"), "champs manquants")); continue
            if any(x.get("source_tweet") == it["source_tweet"] or x.get("topic_key") == it["topic_key"]
                   for x in p["posts"] if x.get("status") in PRIS):
                res["ignores"].append((it["topic_key"], "déjà monté ou publié")); continue
            ex = next((e for e in q["candidates"] if e.get("topic_key") == it["topic_key"] or e.get("source_tweet") == it["source_tweet"]), None)
            if ex:
                if ex["status"] in CLOSED: res["ignores"].append((it["topic_key"], f"déjà {ex['status']}")); continue
                ex["mentions"] = sorted(set(ex.get("mentions", [])) | set(it.get("mentions", [it["origin"]])))
                ex["score"] = max(ex["score"], it["score"]); res["fusionnes"].append(ex["id"]); e = ex
            else:
                src = parse(it["source_time_utc"])
                ttl_h = c["ttl_hours"]; ttl = ttl_h.get(it.get("nature") or "defaut", ttl_h.get("defaut", 12))
                sid = re.sub(r"[^a-z0-9]+", "-", it["topic_key"].lower())[:40].strip("-")
                e = {"id": f"c-{t.strftime('%Y%m%d-%H%M')}-{sid}", "added_at_utc": iso(t),
                     "found_by": it.get("found_by", "veille"), "type": it["type"], "nature": it.get("nature", ""), "topic": it["topic"],
                     "topic_key": it["topic_key"], "origin": it["origin"], "source_tweet": it["source_tweet"],
                     "primary_source": it.get("primary_source", it["source_tweet"]), "source_time_utc": it["source_time_utc"],
                     "expires_at_utc": iso(src + dt.timedelta(hours=ttl)), "fiabilite": it.get("fiabilite", "🟡"),
                     "score": it["score"], "mentions": sorted(set(it.get("mentions", [it["origin"]]))),
                     "media_url": it.get("media_url", ""), "media_repo_path": "", "angle": it.get("angle", ""),
                     "titles": it.get("titles", []), "checks": it.get("checks", []),
                     "photo_needed": it.get("photo_needed", ""), "status": "en_attente", "note": it.get("note", "")}
                q["candidates"].append(e); res["ajoutes"].append(e["id"])
            hr = it.get("hot_reason")
            age_h = (t - parse(e["source_time_utc"])).total_seconds() / 3600
            if hr and not e.get("hot") and e["status"] == "en_attente":
                e["hot"] = True; e["hot_reason"] = hr; res["hot"].append({"id": e["id"], "reason": hr, "topic": e["topic"]})
        m = load(M, {}); m["last_veille_utc"] = iso(t); save(M, m)
        save(Q, q); save(P, p)
        res["menage"] = {"expires": n_exp, "supprimes": n_del, "en_attente": sum(1 for e in q["candidates"] if e["status"] == "en_attente")}
    transact(apply, f"queue: +{len(res['ajoutes'])} fusion {len(res['fusionnes'])}")
    out(res)

def rank(q, p):
    c = cfg(); t = now(); posts = p["posts"]
    cands = []
    for e in q["candidates"]:
        if e["status"] != "en_attente" or covered(e, posts) or e.get("photo_needed"): continue
        age = (t - parse(e["source_time_utc"])).total_seconds() / 3600
        bonus = 1 if age < 2 else (0 if age < 4 else -1)
        cands.append((e["score"] + bonus, e, age))
    cands.sort(key=lambda x: -x[0])
    return cands

def cmd_slot(a):
    c = cfg(); res = {"reseau_ok": network_ok()}
    def apply():
        q, p = qload(), pload(); ménage(q, p); save(Q, q); save(P, p)
    transact(apply, "queue: ménage (créneau)")
    q, p = qload(), pload(); n, last = today_stats(p["posts"]); t = now()
    h = t.astimezone(PARIS).hour + t.astimezone(PARIS).minute / 60
    slot = min(c["slots"], key=lambda s: abs(int(s[:2]) - h))
    res.update({"heure_paris": t.astimezone(PARIS).strftime("%H:%M"), "creneau": slot, "posts_aujourdhui": n})
    stop = None
    if not res["reseau_ok"]: stop = "réseau bloqué (video.twimg.com)"
    elif n >= c["cap_per_day"]: stop = f"plafond de {c['cap_per_day']} posts atteint"
    elif not a.hot and last and (t - last).total_seconds() < c["min_gap_min"] * 60: stop = f"post publié il y a {int((t - last).total_seconds() / 60)} min"
    busy = [x for x in p["posts"] if x.get("status") == "en_cours" and post_time(x) and (t - post_time(x)).total_seconds() < 1800]
    if not stop and busy: stop = f"post en cours ({busy[0]['id']})"
    if stop: res["stop"] = stop; out(res); return
    cands = rank(q, p)
    if a.hot: cands = [x for x in cands if x[1].get("hot")]
    res["candidats"] = [{"id": e["id"], "type": e["type"], "score": e["score"], "score_fraicheur": round(s, 1),
                         "age_h": round(age, 1), "topic": e["topic"], "origin": e["origin"], "fiabilite": e["fiabilite"],
                         "mentions": len(e["mentions"]), "angle": e["angle"], "titles": e["titles"], "checks": e["checks"],
                         "source_tweet": e["source_tweet"], "mp4_repo": e.get("media_repo_path") or None,
                         "media_url": bool(e.get("media_url"))} for s, e, age in cands[:3]]
    res["en_attente_total"] = len(cands)
    out(res)

def next_slot(t, slots):
    """Prochain créneau de publication (heure de Paris) après t."""
    loc = t.astimezone(PARIS)
    for d in (0, 1):
        for s in sorted(slots):
            x = (loc + dt.timedelta(days=d)).replace(hour=int(s[:2]), minute=0, second=0, microsecond=0)
            if x > loc: return x.astimezone(dt.timezone.utc)

def produits_session(posts, t):
    """Vidéos (hors urgences) montées depuis moins de 4 h = session de production en cours."""
    return [x for x in posts if not x.get("urgent") and x.get("status") in PRIS and x.get("proposed_at_utc")
            and (t - parse(x["proposed_at_utc"])).total_seconds() < 4 * 3600]

def cmd_lot(a):
    """Session de production : les meilleurs candidats encore frais au prochain créneau (4 vidéos max)."""
    c = cfg(); res = {"reseau_ok": network_ok()}
    def apply():
        q, p = qload(), pload(); ménage(q, p); save(Q, q); save(P, p)
    transact(apply, "queue: ménage (production)")
    q, p = qload(), pload(); t = now(); maxi = c.get("lot_max", 4)
    reste = maxi - len(produits_session(p["posts"], t))
    slot = next_slot(t, c["slots"])
    res.update({"a_produire": max(0, reste), "prochain_creneau_paris": slot.astimezone(PARIS).strftime("%d/%m %H:%M"),
                "en_validation": sum(1 for x in p["posts"] if x.get("status") in ("a_valider", "valide"))})
    res["retouches"] = [{"post": x["id"], "demande": x.get("demande"), "titre": x.get("titre"), "clip": x.get("clip")}
                        for x in p["posts"] if x.get("status") == "retouche"]
    if not res["reseau_ok"]: res["stop"] = "réseau bloqué (video.twimg.com)"
    elif reste <= 0: res["stop"] = f"déjà {maxi} vidéos produites pour cette session"
    if res.get("stop"): out(res); return
    cands = [x for x in rank(q, p) if parse(x[1]["expires_at_utc"]) > slot + dt.timedelta(minutes=5)]
    res["candidats"] = [{"id": e["id"], "score": e["score"], "nature": e.get("nature"), "age_h": round(age, 1),
                         "expire_paris": parse(e["expires_at_utc"]).astimezone(PARIS).strftime("%d/%m %H:%M"),
                         "topic": e["topic"], "origin": e["origin"], "mentions": len(e["mentions"]), "angle": e["angle"],
                         "titles": e["titles"], "checks": e["checks"], "source_tweet": e["source_tweet"]}
                        for s, e, age in cands[:reste + 2]]
    res["en_attente_total"] = len(cands)
    out(res)

def cmd_proposer(a):
    """Le montage est fait et poussé : envoi en validation. Le sujet SORT de la file (demande d'Alix)."""
    d = json.load(open(a.fiche, encoding="utf-8"))
    for k in ("titre", "legende", "judge"):
        if not d.get(k): raise SystemExit(f"fiche incomplète : « {k} » manque")
    meta = load(f"{ROOT}/posts/{a.post}/{a.post}_montage.json")
    if not meta: raise SystemExit("pas de _montage.json : lancer le montage puis `push` avant `proposer`")
    verdict = (d.get("garde_fou") or "").upper()
    if meta["format"] == "9:16" and verdict not in ("OK", "SPONSOR"): raise SystemExit("garde_fou OK ou SPONSOR requis en 9:16")
    def apply():
        q, p = qload(), pload(); x = next(i for i in p["posts"] if i["id"] == a.post); t = now(); c = cfg()
        if x["status"] != "en_cours": raise SystemExit(f"{a.post} est {x['status']}")
        if not a.urgent and len(produits_session(p["posts"], t)) >= c.get("lot_max", 4):
            raise SystemExit(f"plafond de {c.get('lot_max', 4)} vidéos par session atteint")
        e = next((i for i in q["candidates"] if i["id"] == x.get("queue_id")), None)
        if e and e.get("clip"): x["clip"] = e["clip"]
        if e: x["topic_key"] = e["topic_key"]; x["expires_at_utc"] = e["expires_at_utc"]; x["nature"] = e.get("nature", "")
        x.setdefault("expires_at_utc", iso(t + dt.timedelta(hours=12)))
        x.update({"status": "a_valider", "proposed_at_utc": iso(t), "titre": d["titre"], "legende": d["legende"],
                  "titres_alt": [s for s in d.get("titres_alt", []) if s and s != d["titre"]][:2],
                  "judge_score": str(d["judge"]), "format": meta["format"], "garde_fou": verdict or "SECOURS"})
        if a.urgent: x["urgent"] = True; x["hot_reason"] = "drama"
        q["candidates"] = [i for i in q["candidates"] if i["id"] != x.get("queue_id")]
        save(P, p); save(Q, q)
    transact(apply, f"validation: {a.post} à valider"); out({"ok": a.post, "statut": "a_valider"})

def fetch_media(mu, dest, offset=0, dur=None):
    """Retélécharge la vidéo source d'un montage (retouche demandée depuis Telegram)."""
    tmp = dest + ".src.mp4"
    if "v.redd.it" in mu:
        base = re.sub(r"/[^/]*\.m3u8$", "", mu.rstrip("/")); ua = "-A 'Mozilla/5.0'"
        for r in (1080, 720, 480, 360):
            if sh(f"curl -sf {ua} -o '{tmp}.v' {base}/CMAF_{r}.mp4 || curl -sf {ua} -o '{tmp}.v' {base}/DASH_{r}.mp4", check=False).returncode == 0: break
        has_a = any(sh(f"curl -sf {ua} -o '{tmp}.a' {base}/{n}.mp4", check=False).returncode == 0
                    for n in ("CMAF_AUDIO_128", "CMAF_AUDIO_64", "DASH_AUDIO_128", "DASH_AUDIO_64"))
        amap = f"-i '{tmp}.a' -map 0:v -map 1:a -c:a aac" if has_a else "-an"
        sh(f"ffmpeg -v error -y -i '{tmp}.v' {amap} -c:v copy '{tmp}'")
    elif re.search(r"twitch\.tv|youtube\.com|youtu\.be|streamable\.com|kick\.com", mu):
        sh(f"yt-dlp -q -f 'bv*[height<=1080]+ba/b[height<=1080]/b' --merge-output-format mp4 -o '{tmp}' '{mu}'")
    else: sh(f"curl -sSfL --retry 3 -A 'Mozilla/5.0' -o '{tmp}' '{mu}'")
    cut = f"-t {dur:.2f}" if dur else ""
    sh(f"ffmpeg -v error -y -ss {max(offset, 0):.2f} -i '{tmp}' {cut} -c:v libx264 -preset veryfast -crf 17 -pix_fmt yuv420p -c:a aac -b:a 192k '{dest}'")

def cmd_renvoyer(a):
    """Retouche libre faite et poussée : la vidéo repart en validation."""
    meta = load(f"{ROOT}/posts/{a.post}/{a.post}_montage.json") or {}
    def apply():
        p = pload(); x = next(i for i in p["posts"] if i["id"] == a.post)
        if x["status"] != "retouche": raise SystemExit(f"{a.post} est {x['status']}")
        x.update({"status": "a_valider", "format": meta.get("format", x.get("format"))})
        for k in ("telegram_msg", "envoi_utc", "demande"): x.pop(k, None)
        save(P, p)
    transact(apply, f"validation: {a.post} retouché"); out({"ok": a.post})

def cmd_take(a):
    e = {}
    def apply():
        q = qload(); x = next(i for i in q["candidates"] if i["id"] == a.id)
        if x["status"] != "en_attente": raise SystemExit(f"{a.id} est {x['status']}")
        x["status"] = "pris"; x["taken_at_utc"] = iso(now()); e.update(x); save(Q, q)
    transact(apply, f"queue: pris {a.id}")
    if e["type"] == "clip":
        src = f"{ROOT}/{e['media_repo_path']}" if e.get("media_repo_path") and os.path.exists(f"{ROOT}/{e['media_repo_path']}") else None
        mu = e.get("media_url") or ""
        tw = {"found": False, "reason": "pas d'heure source"}
        native_twitch = bool(re.search(r"clips\.twitch\.tv/|twitch\.tv/[^/]+/clip/", mu))
        if src: sh(f"cp '{src}' /tmp/clip.mp4")
        elif native_twitch or re.search(r"youtube\.com|youtu\.be|streamable\.com|kick\.com", mu):
            # clip trouvé directement à la source (veille Twitch / Reddit) : version d'origine en qualité max
            sh("pip install -q --break-system-packages -U yt-dlp >/dev/null 2>&1 || true", check=False)
            sh(f"rm -f /tmp/clip_dl.*; yt-dlp -q -f 'bv*[height<=1080]+ba/b[height<=1080]/b' --merge-output-format mp4 -o '/tmp/clip_dl.%(ext)s' '{mu}'")
            sh("ffmpeg -v error -y -i /tmp/clip_dl.mp4 -c:v libx264 -preset veryfast -crf 17 -pix_fmt yuv420p -c:a aac -b:a 192k /tmp/clip.mp4")
            if native_twitch:
                ch = re.search(r"twitch\.tv/([^/]+)/clip/", mu); ch = ch.group(1).lower() if ch else (e.get("origin") or "").lower()
                tw = {"found": True, "source": "twitch_direct", "twitch_url": mu, "channel": ch, "credit": f"twitch.tv/{ch}"}
        elif "v.redd.it" in mu:
            # Reddit refuse ffmpeg : fichiers CMAF directs (meilleure définition dispo + son), puis fusion
            base = re.sub(r"/[^/]*\.m3u8$", "", mu.rstrip("/")); ua = "-A 'Mozilla/5.0'"
            for r in (1080, 720, 480, 360):
                if sh(f"curl -sf {ua} -o /tmp/rv.mp4 {base}/CMAF_{r}.mp4 || curl -sf {ua} -o /tmp/rv.mp4 {base}/DASH_{r}.mp4", check=False).returncode == 0: break
            has_a = any(sh(f"curl -sf {ua} -o /tmp/ra.mp4 {base}/{n}.mp4", check=False).returncode == 0
                        for n in ("CMAF_AUDIO_128", "CMAF_AUDIO_64", "DASH_AUDIO_128", "DASH_AUDIO_64"))
            amap = "-i /tmp/ra.mp4 -map 0:v -map 1:a -c:a aac -b:a 192k" if has_a else "-an"
            sh(f"ffmpeg -v error -y -i /tmp/rv.mp4 {amap} -c:v libx264 -preset veryfast -crf 17 -pix_fmt yuv420p /tmp/clip.mp4")
        else: sh(f"curl -sSfL --retry 3 -A 'Mozilla/5.0' -o /tmp/clip.mp4 '{mu}'")
        # source d'origine Twitch (1080p60 + version verticale) si le même moment existe en clip Twitch ; sinon on garde X
        if not tw.get("found") and e.get("source_time_utc") and not getattr(a, "no_twitch", False) and "x.com" in (e.get("source_tweet") or "") + (e.get("primary_source") or ""):
            r = subprocess.run([sys.executable, f"{ROOT}/scripts/twitch_source.py", "upgrade", "--clip", "/tmp/clip.mp4",
                                "--origin", e.get("origin", ""), "--time", e["source_time_utc"]],
                               capture_output=True, text=True, timeout=900)
            try: tw = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception: tw = {"found": False, "reason": (r.stderr or "sortie illisible")[-300:]}
        d = sh("ffprobe -v error -show_entries format=duration,size:stream=width,height -of default=nw=1 /tmp/clip.mp4").stdout.split()
        # d'où vient exactement /tmp/clip.mp4 : permet une retouche sans Claude
        if tw.get("found"): src_info = {"url": tw["twitch_url"], "offset": tw.get("offset_s", 0),
                                        "dur": None if tw.get("source") == "twitch_direct" else float(next(l.split("=")[1] for l in d if l.startswith("duration=")))}
        else: src_info = {"url": mu, "offset": 0, "dur": None}
        if src_info["url"]:
            def note():
                q = qload(); x = next(i for i in q["candidates"] if i["id"] == a.id); x["clip"] = src_info; save(Q, q)
            transact(note, f"queue: source {a.id}")
        out({"id": a.id, "clip": "/tmp/clip.mp4", "ffprobe": d, "origin": e["origin"], "titles": e["titles"], "twitch": tw})
    else: out({"id": a.id, "type": "actu", "topic": e["topic"], "checks": e["checks"], "titles": e["titles"]})

def next_number(p):
    nums = [int(m.group(1)) for x in p["posts"] if (m := re.match(r"(\d{4})-", x["id"]))]
    if os.path.isdir(f"{ROOT}/posts"):
        nums += [int(m.group(1)) for d in os.listdir(f"{ROOT}/posts") if (m := re.match(r"(\d{4})-", d))]
    return max(nums, default=0) + 1

def cmd_reserve(a):
    name = {}
    def apply():
        q, p = qload(), pload(); e = next((i for i in q["candidates"] if i["id"] == a.id), None)
        nm = f"{next_number(p):04d}-{now().astimezone(PARIS).strftime('%d_%m_%Y')}-{a.categorie}"
        p["posts"].append({"id": nm, "status": "en_cours", "type": a.type, "topic": (e or {}).get("topic", a.id),
                           "origin": (e or {}).get("origin", ""), "source_tweet": (e or {}).get("source_tweet", ""),
                           "queue_id": a.id, "reserved_at_utc": iso(now())})
        if e: e["post_id"] = nm
        save(P, p); save(Q, q); name["n"] = nm
    transact(apply, f"journal: réserve {a.id}")
    out({"post": name["n"]})

def cmd_done(a):
    def apply():
        q, p = qload(), pload(); x = next(i for i in p["posts"] if i["id"] == a.post)
        x.update({"status": "publie", "published_at_utc": iso(now())})
        for k, v in (("instagram", a.ig), ("tiktok", a.tiktok), ("zernio_post_id", a.zernio), ("judge_score", a.judge), ("slot", a.slot), ("note", a.note)):
            if v: x[k] = v
        if a.hot: x["hot"] = True; x["hot_reason"] = a.hot
        e = next((i for i in q["candidates"] if i["id"] == x.get("queue_id")), None)
        if e: e["status"] = "publie"; e["post_id"] = a.post; e["closed_at_utc"] = iso(now())
        save(P, p); save(Q, q)
    transact(apply, f"journal: publié {a.post}"); out({"ok": a.post})

def cmd_fail(a):
    def apply():
        q, p = qload(), pload(); x = next(i for i in p["posts"] if i["id"] == a.post)
        x["status"] = "echec"; x["note"] = a.raison
        e = next((i for i in q["candidates"] if i["id"] == x.get("queue_id")), None)
        if e and e["status"] == "pris": e["status"] = "en_attente"
        save(P, p); save(Q, q)
    transact(apply, f"journal: échec {a.post}"); out({"ok": a.post})

def cmd_drop(a):
    def apply():
        q = qload(); e = next(i for i in q["candidates"] if i["id"] == a.id)
        e["status"] = "ecarte"; e["note"] = a.raison; e["closed_at_utc"] = iso(now()); save(Q, q)
    transact(apply, f"queue: écarté {a.id}"); out({"ok": a.id})

def cmd_push(a):
    push_paths(a.message, " ".join(a.paths)); out({"ok": True})

def cmd_status(a):
    q, p = qload(), pload(); n, last = today_stats(p["posts"])
    out({"file": {s: sum(1 for e in q["candidates"] if e["status"] == s) for s in ("en_attente", "pris", "publie", "expire", "ecarte")},
         "posts_aujourdhui": n, "dernier_post": iso(last) if last else None})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    for n in ("queries", "status"): sp.add_parser(n)
    s = sp.add_parser("sources"); s.add_argument("-n", type=int, default=20)
    s = sp.add_parser("slot"); s.add_argument("--hot", action="store_true")
    sp.add_parser("lot")
    s = sp.add_parser("proposer"); s.add_argument("post"); s.add_argument("fiche"); s.add_argument("--urgent", action="store_true")
    s = sp.add_parser("add"); s.add_argument("file", nargs="?")
    s = sp.add_parser("take"); s.add_argument("id"); s.add_argument("--no-twitch", action="store_true")
    s = sp.add_parser("reserve"); s.add_argument("id"); s.add_argument("type", choices=["reel"]); s.add_argument("categorie")
    s = sp.add_parser("done"); s.add_argument("post")
    for k in ("ig", "tiktok", "zernio", "judge", "slot", "hot", "note"): s.add_argument(f"--{k}")
    s = sp.add_parser("fail"); s.add_argument("post"); s.add_argument("raison")
    s = sp.add_parser("drop"); s.add_argument("id"); s.add_argument("raison")
    s = sp.add_parser("renvoyer"); s.add_argument("post")
    s = sp.add_parser("push"); s.add_argument("message"); s.add_argument("paths", nargs="+")
    a = ap.parse_args(); globals()["cmd_" + a.cmd](a)
