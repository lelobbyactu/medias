#!/usr/bin/env python3
"""Le Lobby — collecte des sources hors X (sans IA), lancée par GitHub Actions toutes les 30 min.

  python3 scripts/sources.py run [--only twitch,reddit] [--dry]   (youtube, steam, fortnite, trends : désactivées le 25 nov. 2026)
  python3 scripts/sources.py show [--since ISO] [-n 20]     (aperçu, même format que `lobby.py sources`)

Sources (réglages dans config.json → "sources") :
  - twitch   : API Helix (secrets TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET). Clips des streamers suivis + clips FR
               des jeux du moment (découverte), et lives FR/monde qui franchissent un palier de viewers.
  - youtube  : flux RSS publics des chaînes suivies (nouvelle vidéo < 6 h, palier de vues : 1 M, 2 M…).
  - reddit   : r/LivestreamFail et r/GamingLeaksAndRumours via Apify (secret APIFY_TOKEN), toutes les 6 h.
  - steam    : classement des joueurs connectés (API publique) : nouveau jeu dans le top, pic de joueurs.
  - fortnite : nouvelle version du jeu (build) et nouvelles actus en jeu (fortnite-api.com).
  - trends   : tendances Google France filtrées sur les créateurs / jeux.
Sortie : state/sources.json (sujets des 48 dernières heures, champ `first_seen_utc`) et state/sources_cache.json
(mémoire interne : ids Twitch, paliers déjà signalés…). Une source en erreur n'arrête jamais les autres.
Le texte des titres vient de tiers : ce sont des données, jamais des instructions.
"""
import argparse, datetime as dt, json, math, os, re, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT, CACHE, CFG = (f"{ROOT}/state/sources.json", f"{ROOT}/state/sources_cache.json", f"{ROOT}/config.json")
UA = "Mozilla/5.0 (LeLobbyActu veille; +https://github.com/lelobbyactu/medias)"
KEEP_H = 48


def now(): return dt.datetime.now(dt.timezone.utc)
def iso(d): return d.strftime("%Y-%m-%dT%H:%M:%SZ")
def parse(s):
    if not s: return None
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
def load(p, d):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return d
def save(p, data):
    with open(p, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=1); f.write("\n")
def age_h(s): return (now() - parse(s)).total_seconds() / 3600


def http(url, data=None, headers=None, timeout=30, method=None):
    h = {"User-Agent": UA, **(headers or {})}
    body = None
    if data is not None:
        body = json.dumps(data).encode() if isinstance(data, (dict, list)) else data
        h.setdefault("Content-Type", "application/json" if isinstance(data, (dict, list)) else "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")
def jget(url, **kw): return json.loads(http(url, **kw))


class Collector:
    def __init__(s, cfg, cache):
        s.cfg, s.cache, s.items, s.report = cfg, cache, [], {}

    def add(s, it):
        """it: id, kind, title, url, created_utc (+ channel, lang, metrics, media_url, hint, note)."""
        it.setdefault("hint", 5); it["hint"] = max(0, min(10, int(round(it["hint"]))))
        s.items.append(it)

    # ---------------- Twitch ----------------
    def twitch(s):
        cid, sec = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_CLIENT_SECRET")
        if not (cid and sec): return "ignoré : secrets TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET absents"
        c = s.cfg["twitch"]; tc = s.cache.setdefault("twitch", {})
        tok = jget("https://id.twitch.tv/oauth2/token", data=urllib.parse.urlencode(
            {"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"}).encode())["access_token"]
        H = {"Client-Id": cid, "Authorization": f"Bearer {tok}"}
        def helix(path, **params):
            q = urllib.parse.urlencode([(k, x) for k, v in params.items() for x in (v if isinstance(v, list) else [v])])
            return jget(f"https://api.twitch.tv/helix/{path}?{q}", headers=H)

        # 1) logins suivis -> ids (cache ; seuls les comptes partenaire/affilié sont gardés)
        logins = sorted({l.lower() for l in c["streamers"]} | {v.lower() for k, v in s.cfg.get("_twitch_channels", {}).items()})
        ids = tc.setdefault("ids", {}); bad = set(tc.get("unknown", []))
        todo = [l for l in logins if l not in ids and l not in bad]
        for i in range(0, len(todo), 100):
            got = {u["login"]: u for u in helix("users", login=todo[i:i + 100])["data"]}
            for l in todo[i:i + 100]:
                u = got.get(l)
                if u and u.get("broadcaster_type") in ("partner", "affiliate"): ids[l] = {"id": u["id"], "name": u["display_name"]}
                else: bad.add(l)
        tc["unknown"] = sorted(bad)
        by_id = {v["id"]: l for l, v in ids.items()}

        # 2) lives : paliers de viewers (FR et monde)
        alerted = tc.setdefault("live_alerts", {})  # stream_id -> plus haut palier signalé
        fr = helix("streams", language="fr", first=100)["data"]
        world = helix("streams", first=20)["data"]
        for st, tiers, scope in [(x, c["live_thresholds_fr"], "FR") for x in fr] + [(x, c["live_thresholds_world"], "monde") for x in world]:
            v = st["viewer_count"]; passed = [t for t in tiers if v >= t]
            if not passed or alerted.get(st["id"], 0) >= passed[-1]: continue
            alerted[st["id"]] = passed[-1]
            s.add({"id": f"twitch-live-{st['id']}-{passed[-1]}", "kind": "twitch_live", "created_utc": iso(now()),
                   "title": f"{st['user_name']} dépasse {passed[-1]:,} viewers en live ({scope})".replace(",", " "),
                   "url": f"https://www.twitch.tv/{st['user_login']}", "channel": st["user_login"], "lang": st.get("language"),
                   "metrics": {"viewers": v, "game": st.get("game_name"), "stream_title": st.get("title", "")[:140],
                               "started_utc": st.get("started_at")},
                   "hint": 6 + passed.__len__() + (1 if st["user_login"] in ids else 0)})
        # ménage des alertes de plus de 3 jours (ids de stream croissants : on garde les 300 derniers)
        tc["live_alerts"] = dict(sorted(alerted.items(), key=lambda kv: int(kv[0]))[-300:])

        # 3) clips
        since = iso(now() - dt.timedelta(hours=c["clip_max_age_h"]))
        dmin, dmax = c["clip_duration_s"]; clips = {}
        for l, v in ids.items():
            try:
                for cl in helix("clips", broadcaster_id=v["id"], started_at=since, first=20)["data"]:
                    if cl["view_count"] >= c["clip_min_views_tracked"]: clips[cl["id"]] = (cl, True)
            except urllib.error.HTTPError: pass
        games = {g["id"]: g["name"] for g in helix("games", name=c["fixed_games"])["data"]}
        for st in fr:
            if st["viewer_count"] >= 2000 and st.get("game_id"): games.setdefault(st["game_id"], st.get("game_name"))
        for gid in list(games)[:25]:
            try:
                for cl in helix("clips", game_id=gid, started_at=since, first=100)["data"]:
                    if (cl.get("language") or "").startswith("fr") and cl["view_count"] >= c["clip_min_views_discovery"]:
                        clips.setdefault(cl["id"], (cl, cl["broadcaster_id"] in by_id))
            except urllib.error.HTTPError: pass
        for cl, tracked in clips.values():
            if not (dmin <= cl.get("duration", 0) <= dmax): continue
            views = cl["view_count"]; vel = views / max(age_h(cl["created_at"]), 0.25)
            s.add({"id": f"twitch-clip-{cl['id']}", "kind": "twitch_clip", "created_utc": cl["created_at"],
                   "title": cl["title"], "url": cl["url"], "media_url": cl["url"],
                   "channel": by_id.get(cl["broadcaster_id"], cl["broadcaster_name"].lower()), "lang": cl.get("language"),
                   "metrics": {"views": views, "views_per_h": int(vel), "duration_s": cl.get("duration"),
                               "game": games.get(cl.get("game_id"), ""), "streamer": cl["broadcaster_name"], "suivi": tracked},
                   "hint": 2 * math.log10(max(views, 1)) - 1 + (1 if tracked else 0)})
        return f"{len(ids)} chaînes suivies, {len(fr)} lives FR lus, {len(clips)} clips retenus"

    # ---------------- YouTube (RSS) ----------------
    def youtube(s):
        c = s.cfg["youtube"]; yc = s.cache.setdefault("youtube", {}); tiers_done = yc.setdefault("tiers", {})
        ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "m": "http://search.yahoo.com/mrss/"}
        n = 0
        for name, cid in c["channels"].items():
            try: root = ET.fromstring(http(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"))
            except Exception: continue
            for e in root.findall("a:entry", ns):
                vid = e.find("yt:videoId", ns).text; pub = e.find("a:published", ns).text
                link = e.find("a:link", ns).get("href"); title = e.find("a:title", ns).text or ""
                st = e.find("m:group/m:community/m:statistics", ns); views = int(st.get("views")) if st is not None else 0
                short = "/shorts/" in link; h = age_h(pub)
                if h > 72: continue
                n += 1
                if not short and h <= c["new_video_max_age_h"]:
                    s.add({"id": f"yt-new-{vid}", "kind": "youtube_video", "created_utc": iso(parse(pub)), "title": title,
                           "url": f"https://www.youtube.com/watch?v={vid}", "channel": name,
                           "metrics": {"views": views, "views_per_h": int(views / max(h, 0.25)), "age_h": round(h, 1)},
                           "hint": 6 + (1 if views / max(h, 0.25) > 100000 else 0)})
                passed = [t for t in c["view_tiers"] if views >= t] if h <= 48 else []
                if passed and tiers_done.get(vid, 0) < passed[-1] and not short:
                    tiers_done[vid] = passed[-1]
                    s.add({"id": f"yt-tier-{vid}-{passed[-1]}", "kind": "youtube_record", "created_utc": iso(now()),
                           "title": f"{name} : « {title} » passe {passed[-1] // 1_000_000} M de vues en {int(h)} h",
                           "url": f"https://www.youtube.com/watch?v={vid}", "channel": name,
                           "metrics": {"views": views, "age_h": round(h, 1)}, "hint": 6 + len(passed)})
        yc["tiers"] = dict(list(tiers_done.items())[-400:])
        return f"{len(c['channels'])} chaînes, {n} vidéos de moins de 72 h"

    # ---------------- Reddit (Apify) ----------------
    def reddit(s):
        tok = os.environ.get("APIFY_TOKEN")
        if not tok: return "ignoré : secret APIFY_TOKEN absent"
        c = s.cfg["reddit"]; rc = s.cache.setdefault("reddit", {})
        last = parse(rc.get("last_run_utc"))
        if last and (now() - last).total_seconds() < c["every_hours"] * 3600 - 600 and not s.force:
            return f"pas encore (dernier passage {rc['last_run_utc']})"
        got = 0
        for sub in c["subs"]:
            url = ("https://api.apify.com/v2/acts/automation-lab~reddit-scraper/run-sync-get-dataset-items?"
                   + urllib.parse.urlencode({"token": tok, "timeout": 120, "maxTotalChargeUsd": c["max_charge_usd"]}))
            body = {"urls": [f"https://www.reddit.com/r/{sub['name']}/"], "sort": "hot", "maxPostsPerSource": sub["max"],
                    "includeComments": False, "includeNsfw": False, "postedAfter": f"{c['max_age_h']} hours"}
            try: rows = json.loads(http(url, data=body, timeout=180))
            except Exception as e: s.report[f"reddit/{sub['name']}"] = f"erreur {e}"; continue
            for p in rows:
                if p.get("isStickied") or (p.get("score") or 0) < sub["min_score"]: continue
                link = p.get("link") or ""; media = ""
                if "v.redd.it" in link: media = link.rstrip("/") + "/HLSPlaylist.m3u8"
                elif re.search(r"clips\.twitch\.tv|twitch\.tv/\w+/clip/", link): media = link
                elif re.search(r"youtube\.com|youtu\.be|streamable\.com|kick\.com", link): media = link
                got += 1
                s.add({"id": f"reddit-{p['id']}", "kind": "reddit", "created_utc": iso(parse(p["createdAt"])),
                       "title": p.get("title", ""), "url": p.get("permalink") or p.get("url"), "channel": f"r/{sub['name']}",
                       "media_url": media, "metrics": {"score": p.get("score"), "comments": p.get("numComments"),
                       "flair": p.get("linkFlairText"), "link": link, "domain": p.get("domain")},
                       "hint": 2 * math.log10(max(p.get("score") or 1, 1)) - 1})
        rc["last_run_utc"] = iso(now())
        return f"{got} posts retenus"

    # ---------------- Steam ----------------
    def steam(s):
        c = s.cfg["steam"]; sc = s.cache.setdefault("steam", {}); names = sc.setdefault("names", {})
        seen = sc.setdefault("seen_top", {}); tiers = sc.setdefault("tiers", {})
        ranks = jget("https://api.steampowered.com/ISteamChartsService/GetGamesByConcurrentPlayers/v1/")["response"]["ranks"][:c["top_n"]]
        today = now().strftime("%Y-%m-%d"); first_run = not seen
        for r in ranks:
            a = str(r["appid"])
            if a not in names:
                try: names[a] = jget(f"https://store.steampowered.com/api/appdetails?appids={a}&filters=basic")[a]["data"]["name"]
                except Exception: names[a] = f"app {a}"
            if r["appid"] in c["ignore_appids"]: seen[a] = today; continue
            if not first_run and a not in seen:
                s.add({"id": f"steam-top-{a}-{today}", "kind": "steam", "created_utc": iso(now()),
                       "title": f"{names[a]} entre dans le top {c['top_n']} Steam ({r['concurrent_in_game']:,} joueurs connectés)".replace(",", " "),
                       "url": f"https://steamdb.info/app/{a}/charts/", "channel": "Steam",
                       "metrics": {"rank": r["rank"], "players": r["concurrent_in_game"], "peak_24h": r["peak_in_game"]}, "hint": 5})
            seen[a] = today
            passed = [t for t in c["peak_tiers"] if r["peak_in_game"] >= t]
            if passed and tiers.get(a, 0) < passed[-1]:
                if not first_run:
                    s.add({"id": f"steam-peak-{a}-{passed[-1]}", "kind": "steam", "created_utc": iso(now()),
                           "title": f"{names[a]} dépasse {passed[-1]:,} joueurs simultanés sur Steam".replace(",", " "),
                           "url": f"https://steamdb.info/app/{a}/charts/", "channel": "Steam",
                           "metrics": {"rank": r["rank"], "peak_24h": r["peak_in_game"]}, "hint": 5 + len(passed)})
                tiers[a] = passed[-1]
        lim = (now() - dt.timedelta(days=7)).strftime("%Y-%m-%d")
        sc["seen_top"] = {k: v for k, v in seen.items() if v >= lim}
        return f"top {len(ranks)} lu" + (" (1er passage : mémorisation seulement)" if first_run else "")

    # ---------------- Fortnite ----------------
    def fortnite(s):
        fc = s.cache.setdefault("fortnite", {})
        build = jget("https://fortnite-api.com/v2/aes")["data"]["build"].replace("++Fortnite+Release-", "")
        if fc.get("build") and fc["build"] != build:
            s.add({"id": f"fortnite-build-{build}", "kind": "fortnite", "created_utc": iso(now()),
                   "title": f"Nouvelle mise à jour Fortnite déployée : {build} (avant : {fc['build']})",
                   "url": "https://www.fortnite.com/news", "channel": "Fortnite", "hint": 6})
        fc["build"] = build
        news = jget("https://fortnite-api.com/v2/news/br?language=fr")["data"]
        known = set(fc.get("motds", []))
        for m in news.get("motds") or []:
            if fc.get("motds") is not None and m["id"] not in known:
                s.add({"id": f"fortnite-news-{m['id']}", "kind": "fortnite", "created_utc": iso(now()),
                       "title": f"Actu Fortnite en jeu : {m.get('title')} — {m.get('body', '')[:120]}",
                       "url": "https://www.fortnite.com/news", "channel": "Fortnite", "media_url": m.get("image", ""), "hint": 4})
        fc["motds"] = [m["id"] for m in news.get("motds") or []]
        return f"build {build}"

    # ---------------- Google Trends FR ----------------
    def trends(s):
        kw = [k.lower() for k in s.cfg.get("trends_keywords", [])]
        t = http("https://trends.google.com/trending/rss?geo=FR"); n = 0
        for it in re.findall(r"<item>(.*?)</item>", t, re.S):
            title = re.search(r"<title>(.*?)</title>", it, re.S).group(1).strip()
            news = " ".join(re.findall(r"<ht:news_item_title>(.*?)</ht:news_item_title>", it, re.S))
            blob = f"{title} {news}".lower()
            if not any(re.search(rf"\b{re.escape(k)}\b", blob) for k in kw): continue
            traffic = re.search(r"<ht:approx_traffic>(.*?)</ht:approx_traffic>", it); n += 1
            url = (re.search(r"<ht:news_item_url>(.*?)</ht:news_item_url>", it) or [None, ""])[1]
            s.add({"id": "trend-" + re.sub(r"[^a-z0-9]+", "-", title.lower())[:50] + "-" + now().strftime("%Y%m%d"),
                   "kind": "trend", "created_utc": iso(now()), "title": f"Tendance Google FR : « {title} » ({traffic.group(1) if traffic else '?'} recherches)",
                   "url": url, "channel": "Google Trends", "metrics": {"articles": news[:200]}, "hint": 4})
        return f"{n} tendances liées"


def cmd_run(a):
    cfg = load(CFG, {}); sc = dict(cfg.get("sources", {})); sc["_twitch_channels"] = {k: v for k, v in cfg.get("twitch_channels", {}).items() if not k.startswith("_")}
    cache = load(CACHE, {}); col = Collector(sc, cache); col.force = a.force
    only = a.only.split(",") if a.only else ["twitch", "reddit"]  # ligne éditoriale du 25 nov. 2026 : Twitch + Reddit seulement
    for name in only:
        try: col.report[name] = getattr(col, name)()
        except Exception as e: col.report[name] = f"erreur : {type(e).__name__} {str(e)[:150]}"
    data = load(OUT, {"_doc": "", "items": []}); t = iso(now())
    data["_doc"] = ("Sujets repérés hors X par scripts/sources.py (GitHub Actions, toutes les 30 min). Lu par la veille via "
                    "`python3 scripts/lobby.py sources`. Ne pas éditer à la main. hint = pré-note mécanique /10.")
    old = {i["id"]: i for i in data.get("items", [])}
    for it in col.items:
        if it["id"] in old:  # déjà vu : on met juste à jour les chiffres
            old[it["id"]].update({k: it[k] for k in ("metrics", "hint", "title") if k in it}); old[it["id"]]["updated_utc"] = t
        else:
            it["first_seen_utc"] = t; old[it["id"]] = it
    items = [i for i in old.values() if age_h(i["first_seen_utc"]) < KEEP_H]
    items.sort(key=lambda i: i["first_seen_utc"])
    data.update({"updated_utc": t, "report": col.report, "items": items[-600:]})
    print(json.dumps({"report": col.report, "nouveaux": sum(1 for i in data["items"] if i["first_seen_utc"] == t),
                      "total": len(data["items"])}, ensure_ascii=False))
    if a.dry:
        for i in sorted(col.items, key=lambda i: -i["hint"])[:25]: print(i["hint"], i["kind"], i["title"][:110], i.get("url"))
        return
    save(OUT, data); save(CACHE, cache)


def brief(items, since=None, n=20):
    """Liste compacte pour la veille : sujets apparus depuis `since`, meilleurs d'abord."""
    sel = [i for i in items if not since or parse(i["first_seen_utc"]) >= since]
    sel.sort(key=lambda i: (-i.get("hint", 0), i["first_seen_utc"]))
    rows = []
    for i in sel[:n]:
        m = i.get("metrics", {})
        keep = {k: m[k] for k in ("views", "views_per_h", "viewers", "score", "comments", "duration_s", "game", "streamer", "suivi", "players", "peak_24h", "flair", "link") if m.get(k) not in (None, "")}
        rows.append({"id": i["id"], "kind": i["kind"], "hint": i.get("hint"), "title": i["title"][:160], "channel": i.get("channel"),
                     "created_utc": i.get("created_utc"), "url": i.get("url"), "media_url": i.get("media_url") or None, **keep})
    return {"total_nouveaux": len(sel), "items": rows}


def cmd_show(a):
    data = load(OUT, {"items": []})
    print(json.dumps(brief(data["items"], parse(a.since) if a.since else None, a.n), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("--only"); r.add_argument("--dry", action="store_true"); r.add_argument("--force", action="store_true", help="ignore l'intervalle de Reddit")
    s = sp.add_parser("show"); s.add_argument("--since"); s.add_argument("-n", type=int, default=20)
    a = ap.parse_args(); {"run": cmd_run, "show": cmd_show}[a.cmd](a)
