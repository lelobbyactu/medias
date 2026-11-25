#!/usr/bin/env python3
"""Le Lobby — remplace un clip récupéré sur X par sa version d'origine Twitch (1080p60 + version verticale).

Pourquoi : les streamers et relais postent sur X des versions 720p recompressées. Le même moment existe
presque toujours en clip Twitch (créé juste avant le tweet), en 1080p60, avec en plus une version 9:16
fournie par Twitch (nette quand le streamer diffuse en double format).

Usage (appelé automatiquement par `lobby.py take`, ou à la main) :
  python3 scripts/twitch_source.py upgrade --clip /tmp/clip.mp4 --origin DomingoTV --time 2026-11-20T17:22:02Z
  python3 scripts/twitch_source.py top --channel domingo --hours 24      # clips Twitch les plus vus (veille)

`upgrade` :
  1. trouve la chaîne Twitch de l'origine (config.json → twitch_channels, sinon le login tel quel) ;
  2. liste les clips de la chaîne créés entre 6 h avant et 10 min après le tweet ;
  3. compare les images de la vidéo X à chaque candidat (empreintes 48x27, corrélation) ;
  4. si un candidat dépasse le seuil (0,90) : télécharge la version paysage en qualité max et la version
     verticale, coupées sur le même passage que la vidéo X, et remplace /tmp/clip.mp4 (l'original X est
     gardé dans /tmp/clip_x.mp4) ; la version verticale va dans /tmp/clip_portrait.mp4.
  Sans correspondance ou en cas d'erreur : ne touche à rien (le clip X reste utilisé). Ne bloque jamais.
Sortie : une ligne JSON (found, twitch_url, channel, score, offset_s, landscape, portrait, credit).
"""
import argparse, datetime as dt, json, os, pathlib, re, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
THRESHOLD = 0.90
MAX_CANDIDATES = 12


def out(d):
    print(json.dumps(d, ensure_ascii=False))


def ensure_ytdlp():
    if shutil.which("yt-dlp"):
        return
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", "-U", "yt-dlp"],
                   check=True, capture_output=True)


def channel_for(origin):
    login = re.split(r"[\s(]", (origin or "").strip().lstrip("@"))[0]
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    m = {k.lower(): v for k, v in cfg.get("twitch_channels", {}).items() if not k.startswith("_")}
    return m.get(login.lower(), login.lower())


def list_clips(channel, rng):
    """Liste des clips (la liste renvoyée par Twitch varie d'un appel à l'autre : on fusionne 3 appels)."""
    seen = {}
    for _ in range(3):
        try:
            r = subprocess.run(["yt-dlp", "--flat-playlist", "-J",
                                f"https://www.twitch.tv/{channel}/clips?filter=clips&range={rng}"],
                               capture_output=True, text=True, timeout=170)
            for e in json.loads(r.stdout).get("entries", []):
                if e.get("url") and e.get("timestamp"):
                    seen[e["url"]] = e
        except Exception:
            pass
        if len(seen) >= 20:
            break
    return list(seen.values())


def frames(path, fps=2, crop=None, w=48, h=27):
    """Empreintes w x h (niveaux de gris, normalisées). `crop` = filtre ffmpeg optionnel (ex. "crop=iw:ih/2:0:ih/2")."""
    import numpy as np
    vf = f"fps={fps}," + (crop + "," if crop else "") + f"scale={w}:{h},format=gray"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf, "-f", "rawvideo", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, h * w).astype(np.float32)
    a -= a.mean(1, keepdims=True)
    a /= a.std(1, keepdims=True) + 1e-6
    return a


def score_and_offset(ref, cand, fps=2):
    """Part de la vidéo X retrouvée dans le candidat (médiane des meilleures corrélations) + décalage en s."""
    import numpy as np
    sim = (ref @ cand.T) / ref.shape[1]
    score = float(np.median(sim.max(1)))
    best = None
    n, m = len(ref), len(cand)
    for k in range(-n + 1, m):  # décalage du début de X dans le candidat
        idx = [(i, i + k) for i in range(n) if 0 <= i + k < m]
        if len(idx) < max(3, n // 2):
            continue
        v = float(np.mean([sim[i, j] for i, j in idx]))
        if best is None or v > best[0]:
            best = (v, k)
    return score, (best[1] / fps if best else 0.0)


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    s = j["streams"][0]
    return {"w": s["width"], "h": s["height"], "fps": s["r_frame_rate"], "dur": round(float(j["format"]["duration"]), 2)}


def download(url, fmt, dest, start, dur):
    tmp = dest + ".full.mp4"
    subprocess.run(["yt-dlp", "-q", "-f", fmt, "-o", tmp, url], check=True, timeout=300)
    # recoupe sur le passage de la vidéo X ; réencodage H.264 (les fichiers Twitch sont en HEVC)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(start, 0):.2f}", "-i", tmp, "-t", f"{dur:.2f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", dest], check=True)
    os.remove(tmp)


def cmd_upgrade(a):
    res = {"found": False}
    try:
        ensure_ytdlp()
        channel = channel_for(a.origin)
        res["channel"] = channel
        t = dt.datetime.fromisoformat(a.time.replace("Z", "+00:00")).timestamp()
        age_h = (dt.datetime.now(dt.timezone.utc).timestamp() - t) / 3600
        clips = list_clips(channel, "24hr" if age_h < 20 else "7d")
        xinfo = probe(a.clip)
        cands = [c for c in clips if t - 6 * 3600 <= c["timestamp"] <= t + 600
                 and (c.get("duration") or 0) >= xinfo["dur"] - 3]
        cands.sort(key=lambda c: abs(c["timestamp"] - (t - 120)))  # le clip est souvent créé ~2 min avant le tweet
        res["candidates"] = len(cands)
        if not cands:
            res["reason"] = "aucun clip Twitch dans la fenêtre"
            return out(res)
        ref = frames(a.clip)
        d = tempfile.mkdtemp()
        best, partial = None, 0.0
        for c in cands[:MAX_CANDIDATES]:
            p = os.path.join(d, re.sub(r"\W", "", c["url"].rsplit("/", 1)[-1])[:40] + ".mp4")
            try:
                subprocess.run(["yt-dlp", "-q", "-f", "360/480/worst", "-o", p, c["url"]], timeout=120, check=True)
                s, off = score_and_offset(ref, frames(p))
                cdur = probe(p)["dur"]
            except Exception:
                continue
            # part du passage X contenue dans le clip Twitch (on exige le passage entier)
            cover = max(0.0, min(off + xinfo["dur"], cdur) - max(off, 0.0)) / xinfo["dur"]
            ok = s >= THRESHOLD and cover >= 0.95
            if ok and (best is None or s > best[0]):
                best = (s, off, c)
            partial = max(partial, s) if not ok else partial
            if ok and s >= 0.97:
                break
        if not best:
            res["reason"] = f"pas de clip Twitch qui contient tout le passage (meilleur score partiel {partial:.2f})"
            return out(res)
        s, off, c = best
        res.update(found=True, twitch_url=c["url"], title=c.get("title"), views=c.get("view_count"),
                   score=round(s, 3), offset_s=off, credit=f"twitch.tv/{channel}")
        if a.dry_run:
            return out(res)
        land = "/tmp/clip_twitch.mp4"
        download(c["url"], "bv*[height>=1080]/best", land, off, xinfo["dur"])
        try:
            download(c["url"], "portrait-972/portrait-720/portrait-480", a.portrait, off, xinfo["dur"])
            res["portrait"] = {"path": a.portrait, **probe(a.portrait)}
        except Exception:
            res["portrait"] = None
        li = probe(land)
        if li["h"] < xinfo["h"]:
            res.update(found=False, reason=f"version Twitch moins bonne ({li['h']}p < {xinfo['h']}p)")
            return out(res)
        shutil.copy(a.clip, "/tmp/clip_x.mp4")
        shutil.move(land, a.clip)
        res["landscape"] = {"path": a.clip, **li}
        res["x_original"] = {"path": "/tmp/clip_x.mp4", **xinfo}
    except Exception as e:  # ne bloque jamais le créneau
        res.update(found=False, reason=f"erreur : {e}")
    out(res)


LOCATE_THRESHOLD = 0.85


def zone_filter(zone):
    """zone = "x,y,w,h" en fractions de l'image du reel (ex. "0,0.5,1,0.5" = moitié basse)."""
    x, y, w, h = [float(v) for v in zone.split(",")]
    return f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}"


def cmd_locate(a):
    """Retrouve le clip Twitch brut d'un reel posté par un autre compte (inspiration d'Alix).
    On compare une ZONE du reel (gameplay ou webcam, indiquée par le juge) aux clips Twitch du streamer créés avant le post.
    Le reel recadre le jeu (souvent en 4:3) : on teste le clip entier écrasé ET son centre en 4:3, on garde le meilleur."""
    res = {"found": False}
    try:
        ensure_ytdlp()
        channel = channel_for(a.channel)
        res["channel"] = channel
        t = dt.datetime.fromisoformat(a.time.replace("Z", "+00:00")).timestamp()
        age_h = (dt.datetime.now(dt.timezone.utc).timestamp() - t) / 3600
        clips = list_clips(channel, "24hr" if age_h < 20 else "7d")
        rinfo = probe(a.reel)
        cands = [c for c in clips if t - a.window_h * 3600 <= c["timestamp"] <= t + 600
                 and (c.get("duration") or 0) >= rinfo["dur"] - 3]
        cands.sort(key=lambda c: -(c.get("view_count") or 0))  # un reel reprend presque toujours un clip qui a buzzé
        res["candidates"] = len(cands)
        if not cands:
            res["reason"] = "aucun clip Twitch dans la fenêtre (autre plateforme, ou moment jamais clippé)"
            return out(res)
        ref = frames(a.reel, crop=zone_filter(a.zone), w=48, h=36)
        d = tempfile.mkdtemp()
        best, partial = None, 0.0
        for c in cands[:MAX_CANDIDATES]:
            p = os.path.join(d, re.sub(r"\W", "", c["url"].rsplit("/", 1)[-1])[:40] + ".mp4")
            try:
                subprocess.run(["yt-dlp", "-q", "-f", "360/480/worst", "-o", p, c["url"]], timeout=120, check=True)
                cdur = probe(p)["dur"]
                s, off = max((score_and_offset(ref, frames(p, crop=cr, w=48, h=36)) for cr in (None, "crop=ih*4/3:ih")),
                             key=lambda x: x[0])
            except Exception:
                continue
            cover = max(0.0, min(off + rinfo["dur"], cdur) - max(off, 0.0)) / rinfo["dur"]
            ok = s >= LOCATE_THRESHOLD and cover >= 0.8  # le reel peut être raccourci : 80 % du passage suffit
            if ok and (best is None or s > best[0]):
                best = (s, off, c)
            if not ok:
                partial = max(partial, s)
            if ok and s >= 0.95:
                break
        if not best:
            res["reason"] = f"pas de clip Twitch qui correspond (meilleur score partiel {partial:.2f})"
            return out(res)
        s, off, c = best
        res.update(found=True, twitch_url=c["url"], title=c.get("title"), views=c.get("view_count"), duration=c.get("duration"),
                   score=round(s, 3), offset_s=off, credit=f"twitch.tv/{channel}",
                   created_utc=dt.datetime.fromtimestamp(c["timestamp"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    except Exception as e:
        res.update(found=False, reason=f"erreur : {e}")
    out(res)


def cmd_top(a):
    ensure_ytdlp()
    clips = list_clips(a.channel, "24hr" if a.hours <= 24 else "7d")
    lim = dt.datetime.now(dt.timezone.utc).timestamp() - a.hours * 3600
    clips = sorted([c for c in clips if c["timestamp"] >= lim], key=lambda c: -(c.get("view_count") or 0))
    out([{"url": c["url"], "title": c.get("title"), "views": c.get("view_count"), "duration": c.get("duration"),
          "created_utc": dt.datetime.fromtimestamp(c["timestamp"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
         for c in clips[:a.n]])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    u = sp.add_parser("upgrade")
    u.add_argument("--clip", default="/tmp/clip.mp4")
    u.add_argument("--origin", required=True, help="compte X d'origine (DomingoTV…) ou login Twitch")
    u.add_argument("--time", required=True, help="heure du tweet source, ISO UTC")
    u.add_argument("--portrait", default="/tmp/clip_portrait.mp4")
    u.add_argument("--dry-run", action="store_true")
    l = sp.add_parser("locate", help="retrouve le clip Twitch brut d'un reel (inspiration)")
    l.add_argument("--reel", required=True); l.add_argument("--channel", required=True, help="streamer (login Twitch ou compte X)")
    l.add_argument("--time", required=True, help="date du post du reel, ISO UTC")
    l.add_argument("--zone", default="0,0.5,1,0.5", help="zone gameplay/webcam du reel en fractions x,y,w,h (défaut : moitié basse)")
    l.add_argument("--window-h", type=int, default=72, help="clips créés jusqu'à N h avant le post")
    t = sp.add_parser("top")
    t.add_argument("--channel", required=True)
    t.add_argument("--hours", type=int, default=24)
    t.add_argument("-n", type=int, default=10)
    a = ap.parse_args()
    {"upgrade": cmd_upgrade, "locate": cmd_locate, "top": cmd_top}[a.cmd](a)
