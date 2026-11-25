#!/usr/bin/env python3
"""Le Lobby — format 16:9 DE SECOURS : le clip tel qu'on le voit en live, titre en haut, sous-titres en bas.

Ligne éditoriale (doc projet claude/ligne-editoriale.md, 25 nov. 2026) : le format principal est le 9:16 de
make_reel_916.py ; ce script ne sert que si la qualité de la webcam ou du gameplay recadré n'est pas acceptable
(refus de make_reel_916.py ou garde-fou NON après une correction). Instagram seul.

Usage :
  python3 scripts/make_reel.py --video clip.mp4 --post 0005-19_11_2026-Clips \
      --title "Il se fait tuer|par un *oiseau*|dans GTA 6" [--start 3 --end 38] [--no-subs | --subs-json F]

- --title : lignes séparées par « | » ; le mot/groupe entre *étoiles* reçoit le surligneur jaune (un seul par titre).
- Sortie : posts/<post>/<post>.mp4 + <post>_cover.jpg + <post>_fond.png (à relire visuellement avant publication).
- Mise en page automatique selon le format du clip : « framed » (clip 16:9, carré, 4:3 : cadre sous le titre)
  ou « cover » (clip vertical 9:16 : plein écran, titre sur dégradé).
- Pas de nombre de vues ni de crédit à l'écran (le crédit est dans la légende).
- Sous-titres automatiques (scripts/subtitles.py, même DA que le 9:16) sous la vidéo, sauf --no-subs.
Prérequis : ffmpeg, ffprobe, python3 + playwright, google-chrome (ou chromium Playwright).
"""
import argparse, html, json, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = pathlib.Path(__file__).resolve().parent / "fonts"
Y = "#F2FF3D"; BG = "#111114"; GREY = "#8A8A93"


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    s = j["streams"][0]
    return int(s["width"]), int(s["height"]), float(j["format"]["duration"])


def title_html(title):
    lines = [l.strip() for l in title.split("|") if l.strip()]
    out = []
    for l in lines:
        esc = html.escape(l)
        esc = re.sub(r"\*(.+?)\*", r"<span class='hl'>\1</span>", esc)
        out.append(f"<div class='ln'>{esc}</div>")
    return "".join(out), len(lines)


def font_face(fam, fname, w):
    return f"@font-face{{font-family:'{fam}';src:url('{(FONTS / fname).as_uri()}') format('woff2');font-weight:{w};}}"


def build_html(layout, title, credit_label, credit, vy, hbox):
    th, nlines = title_html(title)
    base = 84 if nlines <= 3 else 70
    css = "".join([font_face("Unbounded", "unbounded-latin-800-normal.woff2", 800),
                   font_face("Unbounded", "unbounded-latin-900-normal.woff2", 900),
                   font_face("Bricolage", "bricolage-grotesque-latin-500-normal.woff2", 500),
                   font_face("Archivo", "archivo-latin-800-normal.woff2", 800)])
    if layout == "framed":
        bg = f"background:{BG};"
        title_top = 270 if vy < 700 else 290
        credit_top = vy + hbox + 34
        extra = f".video{{position:absolute;left:0;top:{vy}px;width:1080px;height:{hbox}px;background:#000}}"
        video_div = "<div class='video'></div>"
        src_style = ""
    else:  # cover : le clip sera dessous, fond transparent + dégradé
        bg = "background:transparent;"
        title_top = 250
        credit_top = 1500
        extra = (f".grad{{position:absolute;left:0;top:0;width:1080px;height:760px;"
                 f"background:linear-gradient(180deg,rgba(17,17,20,.92) 0%,rgba(17,17,20,.7) 55%,rgba(17,17,20,0) 100%)}}")
        video_div = "<div class='grad'></div>"
        src_style = f"background:rgba(17,17,20,.72);padding:8px 18px 8px 16px;border-radius:4px;"
    src_div = (f"<div class='src'><b>{html.escape(credit_label.upper())}</b><span>{html.escape(credit)}</span></div>"
               if credit else "")
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;{bg}overflow:hidden}}
body{{position:relative;color:#fff;font-family:Bricolage}}
{extra}
.logo{{position:absolute;left:64px;top:150px;background:{Y};color:{BG};font-family:Unbounded;font-weight:900;font-size:24px;line-height:.98;padding:10px 12px 9px;border-radius:5px;z-index:3}}
.title{{position:absolute;left:0;right:0;top:{title_top}px;text-align:center;font-family:Unbounded;font-weight:800;text-transform:uppercase;font-size:{base}px;line-height:1.14;letter-spacing:-.5px;z-index:3;{'text-shadow:0 2px 14px rgba(0,0,0,.55);' if layout=='cover' else ''}}}
.ln{{white-space:nowrap;display:block;width:max-content;margin:0 auto}}
.hl{{background:{Y};color:{BG};padding:0 .14em;text-shadow:none;-webkit-box-decoration-break:clone;box-decoration-break:clone}}
.src{{position:absolute;left:64px;top:{credit_top}px;border-left:4px solid {Y};padding:2px 0 2px 16px;font-weight:500;font-size:30px;color:#E6E6EA;display:flex;gap:14px;align-items:baseline;z-index:3;{src_style}}}
.src b{{font-family:Archivo;font-weight:800;font-size:20px;letter-spacing:3px;color:{GREY}}}
</style></head><body>
{video_div}
<div class='logo'>LE<br>LOBBY</div>
<div class='title' id='t'>{th}</div>
{src_div}
</body></html>"""


def render_png(html_text, out_png, transparent):
    from playwright.sync_api import sync_playwright
    f = out_png.with_suffix(".html")
    f.write_text(html_text, encoding="utf-8")
    with sync_playwright() as p:
        kw = {"args": ["--allow-file-access-from-files", "--no-sandbox"]}
        chrome = pathlib.Path("/usr/bin/google-chrome")
        if chrome.exists():
            kw["executable_path"] = str(chrome)
        b = p.chromium.launch(**kw)
        pg = b.new_page(viewport={"width": 1080, "height": 1920})
        pg.goto(f.as_uri())
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(500)
        # ajuste la taille du titre pour tenir dans 940 px de large
        pg.evaluate("""() => {
          const t = document.getElementById('t'); let fs = parseFloat(getComputedStyle(t).fontSize);
          const maxw = () => Math.max(...[...t.querySelectorAll('.ln')].map(e => e.getBoundingClientRect().width));
          let guard = 0; while (maxw() > 940 && fs > 40 && guard++ < 60) { fs -= 2; t.style.fontSize = fs + 'px'; }
        }""")
        pg.wait_for_timeout(150)
        pg.screenshot(path=str(out_png), omit_background=transparent)
        b.close()
    f.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--post", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--credit-label", default="CLIP")
    ap.add_argument("--credit", default="", help="obsolète : le crédit va dans la légende, pas à l'écran")
    ap.add_argument("--no-subs", action="store_true", help="sans sous-titres")
    ap.add_argument("--subs-json", default=None, help="mots corrigés (<nom>_soustitres.json) : pas de nouvelle transcription")
    ap.add_argument("--start", type=float, default=None)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--layout", choices=["auto", "framed", "cover"], default="auto")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args()

    w, h, dur = probe(a.video)
    aspect = w / h
    layout = a.layout if a.layout != "auto" else ("cover" if aspect < 0.8 else "framed")
    start = a.start or 0.0
    end = a.end if a.end is not None else dur
    length = end - start
    if length <= 0:
        sys.exit("durée nulle : vérifier --start/--end")
    if length > 90:
        sys.exit(f"clip trop long ({length:.0f} s) : couper à 90 s maximum avec --start/--end (idéal 15-60 s)")

    hbox = 608
    vy = 730
    if layout == "framed":
        hbox = int(round(1080 / aspect / 2) * 2)
        hbox = max(608, min(1180, hbox))
        vy = 730 if hbox <= 640 else 560
        if vy + hbox > 1700:
            vy = 1700 - hbox

    out_dir = pathlib.Path(a.out_dir) if a.out_dir else ROOT / "posts" / a.post
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{a.post}_fond.png"
    mp4 = out_dir / f"{a.post}.mp4"
    cover = out_dir / f"{a.post}_cover.jpg"

    render_png(build_html(layout, a.title, a.credit_label, a.credit, vy, hbox), png, transparent=(layout == "cover"))

    rep = {}
    subs = ""
    if not a.no_subs:   # sous-titres en bas : sous la vidéo (framed) ou en bas de l'écran (cover)
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import subtitles
        words = subtitles.load_words(a.subs_json) if a.subs_json else subtitles.transcribe(a.video, start, length)
        if words:
            if not a.subs_json:
                subtitles.save_words(words, out_dir / f"{a.post}_soustitres.json")
            rep["mots_incertains"] = [x[2] for x in words if x[3] < 0.5 and len(x[2]) > 3]
            ass = out_dir / f"{a.post}_soustitres.ass"
            sub_y = min(vy + hbox + 90, 1760) if layout == "framed" else 1560
            blocks = subtitles.write_ass(words, ass, sub_y, length)
            subs = f",subtitles={ass}:fontsdir={FONTS}"
            rep["sous_titres"] = " | ".join(" ".join(subtitles.censor(x[2]) for x in b) for b in blocks)
        else:
            rep["sous_titres"] = "aucune parole détectée"
    if layout == "framed":
        fc = (f"[1:v]scale=1080:{hbox}:force_original_aspect_ratio=decrease,pad=1080:{hbox}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v];"
              f"[0:v][v]overlay=0:{vy}:shortest=1{subs},format=yuv420p[o]")
    else:
        fc = ("[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30[v];"
              f"[v][0:v]overlay=0:0:shortest=1{subs},format=yuv420p[o]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(png),
           "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", a.video, "-filter_complex", fc,
           "-map", "[o]", "-map", "1:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", "-shortest", str(mp4)]
    subprocess.run(cmd, check=True)
    t_cover = min(2.0, length / 3)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t_cover:.2f}", "-i", str(mp4), "-frames:v", "1", "-q:v", "3", str(cover)], check=True)
    od, _, od_dur = probe(mp4)
    has_audio = bool(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(mp4)],
                                    capture_output=True, text=True).stdout.strip())
    print(json.dumps({"mp4": str(mp4), "cover": str(cover), "fond": str(png), "layout": layout,
                      "source": f"{w}x{h}", "duration_s": round(od_dur, 1), "has_audio": has_audio,
                      "size_mb": round(mp4.stat().st_size / 1e6, 1), **rep}, ensure_ascii=False))


if __name__ == "__main__":
    main()
