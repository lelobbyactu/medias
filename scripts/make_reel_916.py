#!/usr/bin/env python3
"""Le Lobby — reel 9:16 « titre + webcam + gameplay » (DA v0.6), format principal des clips sur Instagram ET TikTok.

Décisions d'Alix (22 nov. 2026) : variante « B » ; même vidéo sur les deux réseaux (un seul post) ; l'ancien format
(`make_reel.py`, clip 16:9 au milieu) ne sert plus qu'en secours ; webcam un peu plus petite et bande noire entre
la webcam et le gameplay pour les futurs sous-titres.

Mise en page 1080x1920 :
  0-400      bande titre (logo + titre Unbounded + surligneur ; le haut, jusqu'à ~130 px, est caché par l'interface TikTok)
  400-880    webcam : pleine largeur (1080x480) si elle est assez nette, sinon plus petite et centrée (agrandissement max x2,8)
  880-1000   bande noire réservée aux sous-titres (milieu de l'écran)
  1000-1810  gameplay recadré en 4:3 (1080x810), placé hors de la webcam et des overlays fixes
  1810-1920  marge (légende des réseaux)
  Sans webcam (IRL, vidéo YouTube, webcam minuscule) : titre, gameplay 4:3 en 470-1280, bande sous-titres en dessous.
Pas de crédit à l'écran : il est dans la légende.

Usage :
  python3 scripts/make_reel_916.py --video /tmp/clip.mp4 --post <nom> --title "Ligne 1|Ligne 2 *mot*" \
      [--start S --end E] [--channel kamet0] [--cam x,y,w,h | --no-cam] [--game-x X] [--save-layout] [--check-only]
Sous-titres automatiques (scripts/subtitles.py) dans la bande du milieu, sauf --no-subs.\nSorties dans posts/<nom>/ : <nom>.mp4, <nom>_cover.jpg, <nom>_fond.png, <nom>_soustitres.ass, <nom>_planche.jpg (planche à faire relire : docs/juge.md §6bis).
Refus (« ok": false, aucune vidéo) → secours `make_reel.py` (Instagram seul) : cinématique (bandes noires > 30 %), pas de place
pour un cadre 4:3 hors webcam, gameplay trop zoomé, passage > 90 s.
« qr": true = QR code vu dans l'image (souvent un sponsor d'overlay) : à traiter comme un sponsor (pas de TikTok).
Coordonnées --cam / --game-x : dans l'espace 1920x1080, quelle que soit la définition de la source.
"""
import argparse, html, json, pathlib, re, subprocess, sys
import numpy as np
import cv2

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = pathlib.Path(__file__).resolve().parent / "fonts"
MODEL = pathlib.Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
Y = "#F2FF3D"; BG = "#111114"
TITLE_H = 400
CAM_ZONE_Y, CAM_ZONE_H = 400, 480           # webcam pleine largeur : 1080x480
SUB_Y, SUB_H = 880, 120                     # bande sous-titres
GAME_Y, GAME_H = 1000, 810                  # gameplay 4:3
NOCAM_GAME_Y = 470
CAM_MAX_UPSCALE = 2.8                       # au-delà, la webcam est affichée plus petite
CAM_MIN_W = 540                             # largeur minimale d'affichage de la webcam
CAM_MIN_SRC = 150                           # webcam plus étroite que ça (px source) : mise en page sans webcam
AW, AH = 1920, 1080                         # espace d'analyse
MIN_ZOOM = 0.70                             # part de la largeur du jeu visible (16:9 normal = 0,75)
MAX_CINEMA = 0.30


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out); s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(j["format"]["duration"]), float(num) / float(den)


def sample_frames(path, start, length, n=16):
    """n images réparties sur le passage, en 1920x1080 BGR."""
    frames = []
    for i in range(n):
        t = start + length * (i + 0.5) / n
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                              "-vf", f"scale={AW}:{AH}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                             capture_output=True).stdout
        if len(raw) == AW * AH * 3:
            frames.append(np.frombuffer(raw, np.uint8).reshape(AH, AW, 3))
    return frames


def letterbox(frames):
    """Part des images avec bandes noires en haut ET en bas (cinématique) + hauteur utile médiane."""
    cine, boxes = 0, []
    for f in frames:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        rows = g.mean(1); rmax = g.max(1)
        dark = (rows < 14) & (rmax < 45)
        top = int(np.argmin(dark)) if not dark.all() else AH
        bot = int(np.argmin(dark[::-1])) if not dark.all() else AH
        if top >= 30 and bot >= 30:
            cine += 1
        boxes.append((top, bot))
    top = int(np.median([b[0] for b in boxes])); bot = int(np.median([b[1] for b in boxes]))
    return cine / max(1, len(frames)), top, bot


def find_faces(frames):
    det = cv2.FaceDetectorYN.create(str(MODEL), "", (960, 540), 0.7, 0.3, 50)
    pts = []
    for i, f in enumerate(frames):
        small = cv2.resize(f, (960, 540))
        det.setInputSize((960, 540))
        _, faces = det.detect(small)
        if faces is None:
            continue
        for fc in faces:
            x, y, w, h = (fc[:4] * 2).tolist()
            pts.append((i, x, y, w, h, float(fc[-1])))
    return pts


def streamer_face(pts, n):
    """Le visage de la webcam = visage présent sur beaucoup d'images au même endroit (les PNJ bougent)."""
    best = None
    for p in pts:
        cx, cy = p[1] + p[3] / 2, p[2] + p[4] / 2
        near = [q for q in pts if abs(q[1] + q[3] / 2 - cx) < 90 and abs(q[2] + q[4] / 2 - cy) < 90]
        frames_hit = len({q[0] for q in near})
        if best is None or frames_hit > best[0]:
            best = (frames_hit, near)
    if not best or best[0] < max(4, int(0.35 * n)):
        return None
    near = best[1]
    return tuple(float(np.median([q[k] for q in near])) for k in (1, 2, 3, 4))


def persistent_edges(frames):
    acc = np.zeros((AH, AW), np.float32)
    for f in frames:
        g = cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (3, 3), 0)
        acc += (cv2.Canny(g, 40, 120) > 0)
    return acc / max(1, len(frames))


def motion_map(frames):
    g = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]).astype(np.float32)
    return g.std(0)


def webcam_rect(face, P, S):
    """Cherche le cadre de la webcam autour du visage : première ligne droite fixe (contour persistant)
    ou premier saut de mouvement (la webcam bouge peu, le jeu beaucoup), dans chaque direction."""
    fx, fy, fw, fh = face
    cx, cy = fx + fw / 2, fy + fh / 2
    y0, y1 = int(max(0, fy - fh)), int(min(AH, fy + 2 * fh))
    ref = float(np.median(S[int(max(0, fy - fh)):int(min(AH, fy + 2 * fh)), int(max(0, fx - 2 * fw)):int(min(AW, fx + 3 * fw))]))
    jump = max(22.0, 2.5 * ref)

    def scan_x(rng):
        for x in rng:
            if P[y0:y1, max(0, x - 1):x + 2].mean() > 0.30 or S[y0:y1, max(0, x - 1):x + 2].mean() > jump:
                return x
        return None

    left = scan_x(range(int(fx - fw * 0.3), max(0, int(fx - 7 * fw)), -1))
    right = scan_x(range(int(fx + fw * 1.3), min(AW, int(fx + 8 * fw))))
    xl = left if left is not None else max(0, int(cx - 3 * fw))
    xr = right if right is not None else min(AW, int(cx + 3 * fw))
    if left is None and cx - 3.6 * fw < 0: xl = 0
    if right is None and cx + 3.6 * fw > AW: xr = AW

    def scan_y(rng):
        for y in rng:
            if P[max(0, y - 1):y + 2, xl:xr].mean() > 0.30 or S[max(0, y - 1):y + 2, xl:xr].mean() > jump:
                return y
        return None

    top = scan_y(range(int(fy - fh * 0.1), max(0, int(fy - 4 * fh)), -1))
    bot = scan_y(range(int(fy + fh * 1.1), min(AH, int(fy + 6 * fh))))
    yt = top if top is not None else max(0, int(cy - 1.6 * fh))
    yb = bot if bot is not None else min(AH, int(cy + 2.6 * fh))
    if top is None and cy - 2.2 * fh < 0: yt = 0
    if bot is None and cy + 3.2 * fh > AH: yb = AH
    w, h = xr - xl, yb - yt
    ok = 180 <= w <= 1100 and 120 <= h <= 800 and 0.9 <= w / h <= 2.6
    if not ok:  # repli : boîte 16:9 centrée sur le visage
        w = int(min(900, max(320, 5 * fw))); h = int(w * 9 / 16)
        xl = int(min(max(0, cx - w / 2), AW - w)); yt = int(min(max(0, cy - h * 0.45), AH - h))
    return [int(xl), int(yt), int(w), int(h)], ok


def static_cam_box(frames, face):
    """Zone de l'image qui bouge peu (fond de la webcam) et qui contient le visage : souvent la webcam entière."""
    st = np.stack([cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (384, 216)).astype(np.float32) for f in frames])
    mask = ((st.std(0) < 8) & (st.mean(0) > 12)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    cx, cy = int((face[0] + face[2] / 2) / 5), int((face[1] + face[3] / 2) / 5)
    best = None
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if x <= cx <= x + w and y <= cy <= y + h:
            r = [int(x * 5), int(y * 5), int(w * 5), int(h * 5)]
            if best is None or r[2] * r[3] < best[2] * best[3]:
                best = r
    return best


def fit_aspect(rect, face, aspect):
    """Rogne la webcam (3 % de marge pour le cadre) au format de la bande, centrée sur le visage."""
    x, y, w, h = rect
    m = 0.03
    x, y, w, h = x + w * m, y + h * m, w * (1 - 2 * m), h * (1 - 2 * m)
    fcx = face[0] + face[2] / 2; fcy = face[1] + face[3] / 2
    if w / h > aspect:
        nw = h * aspect; x = min(max(x, fcx - nw / 2), x + w - nw); w = nw
    else:
        nh = w / aspect; y = min(max(y, fcy - nh * 0.45), y + h - nh); h = nh
    return [int(x), int(y), int(w), int(h)]


def static_overlays(frames, exclude):
    """Zones fixes (logos, bandeaux, compteurs) hors webcam et hors bandes noires."""
    st = np.stack([cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (384, 216)).astype(np.float32) for f in frames])
    mask = ((st.std(0) < 5) & (st.mean(0) > 30)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    ex = [e for e in exclude]
    out = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < 150:
            continue
        r = [int(x * 5), int(y * 5), int(w * 5), int(h * 5)]
        if any(inter(r, e) > 0.5 * r[2] * r[3] for e in ex):
            continue
        out.append(r)
    return out


def inter(a, b):
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]); h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def game_window(cam, overlays, top, bot):
    """Cadre 4:3 sur toute la hauteur utile, qui ne touche pas la webcam ; le moins d'overlays possible, centré sinon."""
    H0 = AH - top - bot if (top >= 30 and bot >= 30) else AH
    Y0 = top if (top >= 30 and bot >= 30) else 0
    for shrink in (1.0, 0.98, 0.96, 0.94):   # si la webcam gêne de peu : cadre un peu plus petit (léger zoom)
        gh = int(H0 * shrink) // 2 * 2; gy = Y0 + (H0 - gh) // 2
        gw = int(round(gh * 4 / 3)) // 2 * 2
        best = None
        for x in range(0, AW - gw + 1, 4):
            r = [x, gy, gw, gh]
            if cam and inter(r, [cam[0] - 4, cam[1] - 4, cam[2] + 8, cam[3] + 8]) > 0:
                continue
            cost = sum(inter(r, o) for o in overlays) / (gw * gh) * 10 + abs(x + gw / 2 - AW / 2) / AW
            if best is None or cost < best[0]:
                best = (cost, r)
        if best:
            return best[1], gw / AW
    return None, 0.0


def qr_found(frames, rects):
    """Vrai QR = lisible, ou petit et carré et vu sur au moins 2 images (évite les faux positifs géants)."""
    det = cv2.QRCodeDetector()
    hits = 0
    for f in frames[::2]:
        for (x, y, w, h) in rects:
            crop = f[y:y + h, x:x + w]
            if crop.size == 0:
                continue
            big = cv2.resize(crop, None, fx=1.5, fy=1.5)
            txt, pts, _ = det.detectAndDecode(big)
            if txt:
                return True
            if pts is None:
                continue
            p = pts.reshape(-1, 2)
            sides = [np.linalg.norm(p[i] - p[(i + 1) % 4]) for i in range(4)]
            area = cv2.contourArea(p.astype(np.float32))
            if min(sides) > 20 and max(sides) / min(sides) < 1.3 and area < 0.10 * big.shape[0] * big.shape[1]:
                hits += 1
                if hits >= 2:
                    return True
    return False


def font_face(fam, fname, w):
    return f"@font-face{{font-family:'{fam}';src:url('{(FONTS / fname).as_uri()}') format('woff2');font-weight:{w};}}"


def render_overlay(title, out_png, logo_xy):
    """Calque transparent : titre DA dans la bande du haut + petit logo (le fond sombre vient de ffmpeg)."""
    lines = [l.strip() for l in title.split("|") if l.strip()]
    th = "".join("<div class='ln'>" + re.sub(r"\*(.+?)\*", r"<span class='hl'>\1</span>", html.escape(l)) + "</div>" for l in lines)
    css = "".join([font_face("Unbounded", "unbounded-latin-800-normal.woff2", 800),
                   font_face("Unbounded", "unbounded-latin-900-normal.woff2", 900)])
    box_h = TITLE_H - 140 - 20
    doc = f"""<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:transparent;overflow:hidden}}
body{{position:relative;color:#fff}}
.logo{{position:absolute;left:{logo_xy[0]}px;top:{logo_xy[1]}px;background:{Y};color:{BG};font-family:Unbounded;font-weight:900;font-size:18px;line-height:.98;padding:8px 9px 7px;border-radius:4px}}
.box{{position:absolute;left:0;right:0;top:140px;height:{box_h}px;padding:0 40px;display:flex;flex-direction:column;justify-content:center}}
.title{{text-align:center;font-family:Unbounded;font-weight:800;text-transform:uppercase;font-size:64px;line-height:1.14;letter-spacing:-.5px}}
.ln{{white-space:nowrap;display:block;width:max-content;margin:0 auto}}
.hl{{background:{Y};color:{BG};padding:0 .14em;-webkit-box-decoration-break:clone;box-decoration-break:clone}}
</style></head><body><div class='box'><div class='title' id='t'>{th}</div></div><div class='logo'>LE<br>LOBBY</div></body></html>"""
    from playwright.sync_api import sync_playwright
    f = out_png.with_suffix(".html"); f.write_text(doc, encoding="utf-8")
    with sync_playwright() as p:
        kw = {"args": ["--allow-file-access-from-files", "--no-sandbox"]}
        if pathlib.Path("/usr/bin/google-chrome").exists():
            kw["executable_path"] = "/usr/bin/google-chrome"
        b = p.chromium.launch(**kw); pg = b.new_page(viewport={"width": 1080, "height": 1920})
        pg.goto(f.as_uri()); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(400)
        fit = pg.evaluate(f"""() => {{
          const t = document.getElementById('t'); let fs = 64;
          const W = () => Math.max(...[...t.querySelectorAll('.ln')].map(e => e.getBoundingClientRect().width));
          while ((W() > 980 || t.getBoundingClientRect().height > {box_h}) && fs > 34) {{ fs -= 2; t.style.fontSize = fs + 'px'; }}
          return fs; }}""")
        pg.wait_for_timeout(100); pg.screenshot(path=str(out_png), omit_background=True); b.close()
    f.unlink()
    return fit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--post", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--start", type=float, default=None); ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--channel", default=None, help="chaîne Twitch (webcam mémorisée)")
    ap.add_argument("--cam", default=None, help="x,y,w,h de la webcam (espace 1920x1080) : correction manuelle")
    ap.add_argument("--no-cam", action="store_true", help="forcer la mise en page sans webcam")
    ap.add_argument("--game-x", type=int, default=None, help="position x du cadre 4:3 : correction manuelle")
    ap.add_argument("--save-layout", action="store_true", help="mémorise la webcam dans config.json (après relecture OK)")
    ap.add_argument("--check-only", action="store_true", help="analyse + planche, sans montage")
    ap.add_argument("--no-subs", action="store_true", help="sans sous-titres")
    ap.add_argument("--subs-json", default=None, help="mots corrigés (<nom>_soustitres.json) : pas de nouvelle transcription")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args()

    W, H, dur, fps = probe(a.video)
    start = a.start or 0.0; end = a.end if a.end is not None else dur; length = end - start
    out_dir = pathlib.Path(a.out_dir) if a.out_dir else ROOT / "posts" / a.post
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = {"ok": False, "reasons": [], "source": f"{W}x{H}@{fps:.0f}"}
    s = W / AW

    def stop(reason):
        rep["reasons"].append(reason + " → secours make_reel.py (Instagram seul)")
        print(json.dumps(rep, ensure_ascii=False)); sys.exit(0)

    if length > 90:
        stop("passage > 90 s : couper avec --start/--end")
    frames = sample_frames(a.video, start, length)
    if len(frames) < 8:
        stop("vidéo illisible")

    cine, top, bot = letterbox(frames)
    rep["cinematique"] = round(cine, 2)
    if cine > MAX_CINEMA:
        stop(f"cinématique ({cine:.0%} du clip avec bandes noires)")

    # --- webcam ---
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    mem = cfg.get("tiktok_layouts", {}).get(a.channel or "", {}) if a.channel else {}
    cam = face = None
    if not a.no_cam:
        face = streamer_face(find_faces(frames), len(frames))
        if a.cam:
            cam = [int(v) for v in a.cam.split(",")]; rep["cam_source"] = "manuel"
            face = face or (cam[0] + cam[2] * 0.4, cam[1] + cam[3] * 0.3, cam[2] * 0.2, cam[3] * 0.3)
        elif mem.get("cam") and face and inter(mem["cam"], list(face)) > 0.6 * face[2] * face[3]:
            cam = mem["cam"]; rep["cam_source"] = "mémorisée"
        elif face:
            cam, clean = webcam_rect(face, persistent_edges(frames), motion_map(frames))
            rep["cam_source"] = "détectée" if clean else "estimée autour du visage"
            B = static_cam_box(frames, face)
            if B:
                ok_b = 200 <= B[2] <= 1000 and 120 <= B[3] <= 700 and 1.0 <= B[2] / B[3] <= 2.4
                if ok_b and inter(B, cam) >= 0.8 * cam[2] * cam[3] and B[2] * B[3] > 1.3 * cam[2] * cam[3]:
                    cam = B; rep["cam_source"] = "détectée (zone fixe)"
    layout = "sans_webcam"
    if cam:
        cam_crop = fit_aspect(cam, face, 1080 / CAM_ZONE_H)
        src_w = cam_crop[2] * s
        if src_w >= CAM_MIN_SRC:
            cw = int(min(1080, max(CAM_MIN_W, src_w * CAM_MAX_UPSCALE))) // 2 * 2
            if cw >= 960:   # à 10 % près, pleine largeur
                cw = 1080
            ch = int(round(cw * CAM_ZONE_H / 1080)) // 2 * 2
            cam_box = [(1080 - cw) // 2, CAM_ZONE_Y + (CAM_ZONE_H - ch) // 2 // 2 * 2, cw, ch]
            layout = "webcam" if cw == 1080 else "webcam_reduite"
            rep["webcam_agrandissement"] = round(cw / src_w, 2)
            rep["webcam_affichee"] = f"{cw}x{ch}"
        else:
            rep["cam_note"] = f"webcam trop petite ({src_w:.0f} px) : mise en page sans webcam"
            cam = None
    rep["layout"] = layout
    rep["cam"] = cam

    # --- gameplay ---
    overlays = static_overlays(frames, [cam] if cam else [])
    rep["overlays_fixes"] = overlays
    if a.game_x is not None:
        gw = int(AH * 4 / 3); win = [a.game_x, 0, gw, AH]; zoom = gw / AW
    else:
        win, zoom = game_window(cam, overlays, top, bot)
    rep["zoom_largeur_visible"] = round(zoom, 2)
    if not win:
        stop("pas de place pour un cadre 4:3 hors de la webcam")
    if zoom < MIN_ZOOM:
        stop(f"gameplay trop zoomé ({zoom:.0%} de la largeur visible)")
    rep["cadre_jeu"] = win
    rep["overlays_dans_cadre"] = [o for o in overlays if inter(o, win) > 0]
    rep["qr"] = qr_found(frames, ([cam_crop] if cam else []) + [win])

    # --- planche : images source annotées (rose = webcam, jaune = jeu, rouge = overlays fixes) ---
    plan = out_dir / f"{a.post}_planche.jpg"
    src = []
    for f in (frames[3], frames[11]):
        im = f.copy()
        if cam:
            cv2.rectangle(im, (cam_crop[0], cam_crop[1]), (cam_crop[0] + cam_crop[2], cam_crop[1] + cam_crop[3]), (180, 60, 255), 6)
        cv2.rectangle(im, (win[0], win[1]), (win[0] + win[2], win[1] + win[3]), (61, 255, 242), 6)
        for o in overlays:
            cv2.rectangle(im, (o[0], o[1]), (o[0] + o[2], o[1] + o[3]), (40, 40, 255), 3)
        src.append(cv2.resize(im, (960, 540)))
    src_row = np.hstack(src)
    if a.save_layout and a.channel and cam:
        cfg.setdefault("tiktok_layouts", {"_doc": "Webcam mémorisée par chaîne Twitch (espace 1920x1080), écrite par make_reel_916.py --save-layout après relecture OK."})
        cfg["tiktok_layouts"][a.channel] = {"cam": cam}
        (ROOT / "config.json").write_text(json.dumps(cfg, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        rep["layout_memorise"] = a.channel
    if a.check_only:
        cv2.imwrite(str(plan), src_row, [cv2.IMWRITE_JPEG_QUALITY, 85])
        rep.update(ok=True, planche=str(plan), check_only=True); print(json.dumps(rep, ensure_ascii=False)); return

    # --- montage ---
    game_y = GAME_Y if cam else NOCAM_GAME_Y
    logo = (cam_box[0] + 20, cam_box[1] + 20) if cam else (24, game_y + 20)
    png = out_dir / f"{a.post}_fond.png"
    rep["titre_px"] = render_overlay(a.title, png, logo)
    mp4 = out_dir / f"{a.post}.mp4"
    subs = ""
    if not a.no_subs:   # sous-titres (scripts/subtitles.py) dans la bande noire du milieu
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import subtitles
        words = subtitles.load_words(a.subs_json) if a.subs_json else subtitles.transcribe(a.video, start, length)
        if words:
            if not a.subs_json:
                subtitles.save_words(words, out_dir / f"{a.post}_soustitres.json")
            rep["mots_incertains"] = [w[2] for w in words if w[3] < 0.5 and len(w[2]) > 3]
            ass = out_dir / f"{a.post}_soustitres.ass"
            blocks = subtitles.write_ass(words, ass, SUB_Y + SUB_H // 2 if cam else NOCAM_GAME_Y + GAME_H + 60, length)
            subs = f",subtitles={ass}:fontsdir={FONTS}"
            rep["sous_titres"] = " | ".join(" ".join(subtitles.censor(x[2]) for x in b) for b in blocks)
        else:
            rep["sous_titres"] = "aucune parole détectée"
    g = [int(round(v * s)) // 2 * 2 for v in win]
    ofps = 60 if fps > 45 else 30
    if cam:
        c = [int(round(v * s)) // 2 * 2 for v in cam_crop]
        fc = (f"[1:v]split=2[a][b];"
              f"[a]crop={c[2]}:{c[3]}:{c[0]}:{c[1]},scale={cam_box[2]}:{cam_box[3]}:flags=lanczos,unsharp=5:5:0.5[c];"
              f"[b]crop={g[2]}:{g[3]}:{g[0]}:{g[1]},scale=1080:{GAME_H}:flags=lanczos,unsharp=5:5:0.3[g];"
              f"color=c=0x111114:s=1080x1920:r={ofps}[bg];[bg][c]overlay={cam_box[0]}:{cam_box[1]}:shortest=1[t1];"
              f"[t1][g]overlay=0:{game_y}:shortest=1[t2];[t2][0:v]overlay=0:0:shortest=1{subs},fps={ofps},format=yuv420p[o]")
    else:
        fc = (f"[1:v]crop={g[2]}:{g[3]}:{g[0]}:{g[1]},scale=1080:{GAME_H}:flags=lanczos,unsharp=5:5:0.3[g];"
              f"color=c=0x111114:s=1080x1920:r={ofps}[bg];[bg][g]overlay=0:{game_y}:shortest=1[t2];"
              f"[t2][0:v]overlay=0:0:shortest=1{subs},fps={ofps},format=yuv420p[o]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(ofps), "-i", str(png),
                    "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", a.video, "-filter_complex", fc,
                    "-map", "[o]", "-map", "1:a?", "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-profile:v", "high",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-shortest", str(mp4)], check=True)
    cover = out_dir / f"{a.post}_cover.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{min(2.0, length / 3):.2f}", "-i", str(mp4),
                    "-frames:v", "1", "-q:v", "3", str(cover)], check=True)
    outs = []
    for k in range(4):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{length * (k + 0.5) / 4:.2f}", "-i", str(mp4), "-frames:v", "1",
                              "-vf", "scale=480:854", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
        outs.append(np.frombuffer(raw, np.uint8).reshape(854, 480, 3))
    cv2.imwrite(str(plan), np.vstack([np.hstack(outs), src_row]), [cv2.IMWRITE_JPEG_QUALITY, 82])
    _, _, odur, _ = probe(mp4)
    has_audio = bool(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name",
                                     "-of", "csv=p=0", str(mp4)], capture_output=True, text=True).stdout.strip())
    rep.update(ok=True, mp4=str(mp4), cover=str(cover), planche=str(plan), duration_s=round(odur, 1),
               has_audio=has_audio, size_mb=round(mp4.stat().st_size / 1e6, 1))
    print(json.dumps(rep, ensure_ascii=False))


if __name__ == "__main__":
    main()
