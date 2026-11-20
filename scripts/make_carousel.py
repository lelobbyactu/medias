#!/usr/bin/env python3
"""Le Lobby — rend un carrousel (DA v0.6, 1080x1350) à partir d'un fichier JSON, en UNE commande.

Usage :
  python3 scripts/make_carousel.py --spec /tmp/spec.json
Sortie : posts/<post>/<post>_01.jpg, _02.jpg, ... (JPG, compatibles Instagram + TikTok photo).
Exemple complet : scripts/exemple_carousel.json (post 0008 validé par Alix le 20 nov. 2026).

Spec :
{
  "post": "0010-20_11_2026-Chiffres",
  "rubrique": "chiffres" | "actu" | "streamers" | "esport" | "leak",
  "image": "assets/keyart/gta6.jpg" ou une URL https d'une image OFFICIELLE (éditeur, plateforme),
  "image_credit": "Rockstar Games",
  "slides": [ {type: ...}, ... ]   (la slide « Abonne-toi » finale est ajoutée si absente)
}
Texte : dans "title", « | » = retour à la ligne, *mot* = surligneur jaune (UN seul groupe par titre).
Dans les autres textes, **mot** = gras blanc. Les espaces insécables sont ajoutés automatiquement
devant : ; ! ? % et entre un nombre et son unité courte (M, Md$, M$, Go, h...).

Types de slides :
- cover    : title, sub, [image_pos "center top"]                         (1re slide, SWIPE →)
- split    : kicker, title, left{value,label}, right{value,label}, share (part de gauche en %), [note]
- bars     : kicker, title, bars[{label, value, num, hot}], [note]           (largeurs proportionnelles à num)
- versus   : kicker, title, left{kicker,value,label}, right{kicker,value,label}, [note], [avis]
- cards    : kicker, title, [text], cards[{value,label,[tag],[tag_color]}], [note], [avis]
- text     : kicker, title, text, [avis]
- subscribe: line
Chaque slide (sauf subscribe) : "source": ["Source" | "Sources" | "Image", "texte court"].
"avis" = encadré jaune « Notre avis » (prise de position franche, séparée des faits).
"""
import argparse, html, json, pathlib, re, shutil, subprocess, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = pathlib.Path(__file__).resolve().parent / "fonts"
Y = "#F2FF3D"; BG = "#111114"; GREY = "#8A8A93"; LINE = "#26262C"; CARD = "#1B1B21"
RUBRIQUES = {"chiffres": ("LES CHIFFRES", "#FFFFFF", BG), "actu": ("ACTU", Y, BG),
             "streamers": ("STREAMERS", "#A270FF", "#FFFFFF"), "esport": ("ESPORT", "#3D7BFF", "#FFFFFF"),
             "leak": ("LEAK", "#FF3B30", "#FFFFFF"), "youtube": ("YOUTUBE", "#FF2D2D", "#FFFFFF")}


def ff(fam, fname, w):
    return f"@font-face{{font-family:'{fam}';src:url('{(FONTS / fname).as_uri()}') format('woff2');font-weight:{w};}}"


CSS = "".join([
    ff("Unbounded", "unbounded-latin-800-normal.woff2", 800), ff("Unbounded", "unbounded-latin-900-normal.woff2", 900),
    ff("Inter", "inter-latin-700-normal.woff2", 700), ff("Archivo", "archivo-latin-800-normal.woff2", 800),
    ff("Bricolage", "bricolage-grotesque-latin-400-normal.woff2", 400),
    ff("Bricolage", "bricolage-grotesque-latin-500-normal.woff2", 500),
    ff("Bricolage", "bricolage-grotesque-latin-600-normal.woff2", 600),
]) + f"""
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1350px;background:{BG};color:#fff;font-family:Bricolage;overflow:hidden}}
.slide{{width:1080px;height:1350px;padding:72px 76px 64px;display:flex;flex-direction:column;position:relative;overflow:hidden}}
.bgimg{{position:absolute;left:0;top:0;width:100%;object-fit:cover}}
.bgfade{{position:absolute;inset:0}}
.z{{position:relative;z-index:2}}
.top{{display:flex;justify-content:space-between;align-items:flex-start}}
.logo{{background:{Y};color:{BG};font-family:Unbounded;font-weight:900;font-size:30px;line-height:.98;padding:12px 15px 11px;border-radius:6px}}
.tag{{font-family:Inter;font-weight:700;font-size:22px;letter-spacing:2px;padding:10px 18px;border-radius:6px;display:inline-block}}
.h{{font-family:Unbounded;font-weight:800;text-transform:uppercase;line-height:1.12;letter-spacing:-.5px}}
.hl{{background:{Y};color:{BG};padding:0 .14em;-webkit-box-decoration-break:clone;box-decoration-break:clone}}
.y{{color:{Y}}}
.sub{{font-weight:500;font-size:36px;line-height:1.35;color:#E6E6EA}}
.kicker{{font-family:Inter;font-weight:700;font-size:24px;letter-spacing:3px;color:{GREY};text-transform:uppercase}}
.src{{border-left:4px solid {Y};padding:2px 0 2px 16px;font-weight:500;font-size:25px;color:#E6E6EA;display:flex;gap:14px;align-items:baseline}}
.src b{{font-family:Archivo;font-weight:800;font-size:18px;letter-spacing:3px;color:{GREY};white-space:nowrap}}
.foot{{margin-top:auto;padding-top:20px}}
.footrow{{display:flex;justify-content:space-between;align-items:center}}
.src+.footrow{{margin-top:16px}}
.handle{{display:inline-block;border:3px solid {Y};color:{Y};font-family:Unbounded;font-weight:800;font-size:26px;padding:9px 18px;border-radius:40px}}
.page{{font-family:Unbounded;font-weight:800;font-size:34px;color:{Y}}}
.swipe{{font-family:Unbounded;font-weight:800;font-size:30px;color:{Y};white-space:nowrap}}
.big{{font-family:Unbounded;font-weight:800;letter-spacing:-2px;line-height:1;white-space:nowrap}}
.lbl{{font-weight:500;font-size:31px;line-height:1.3;color:#D9D9DE}}
.lbl b,.sub b{{font-weight:600;color:#fff}}
.card{{border-top:2px solid {LINE};padding:28px 0}}
.box{{background:{CARD};border-radius:18px;padding:28px 30px}}
.cta{{background:{Y};color:{BG};border-radius:16px;padding:30px 34px}}
.cta .h{{font-size:40px}}
"""

NBSP_RULES = [(r" ([:;!?%»])", "\u00a0\\1"), (r"« ", "«\u00a0"),
              (r"(\d) (M\$|Md\$|M€|Md€|M|Md|Go|To|K|h|min|ans|%)(?=[\s.,;:!?)]|$)", "\\1\u00a0\\2"),
              (r"(\d\u00a0h) (\d)", "\\1\u00a0\\2")]


def fmt(t, title=False):
    t = html.escape(t or "")
    for a, b in NBSP_RULES:
        t = re.sub(a, b, t)
    if title:
        t = re.sub(r"\*(.+?)\*", r"<span class='hl'>\1</span>", t)
        t = t.replace("|", "<br>")
    else:
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t


class Deck:
    def __init__(self, spec):
        self.spec = spec
        self.rub = RUBRIQUES.get(spec.get("rubrique", "actu"), RUBRIQUES["actu"])
        self.img = spec["_image_uri"]
        self.credit = spec.get("image_credit", "")

    def tag(self):
        t, bg, fg = self.rub
        return f"<div class='tag' style='background:{bg};color:{fg}'>{t}</div>"

    def top(self, z=False):
        return f"<div class='top{' z' if z else ''}'><div class='logo'>LE<br>LOBBY</div>{self.tag()}</div>"

    @staticmethod
    def src(s):
        return f"<div class='src'><b>{html.escape(s[0].upper())}</b><span>{fmt(s[1])}</span></div>" if s else ""

    def foot(self, s, n, total, swipe=False):
        right = "<div class='swipe'>SWIPE →</div>" if swipe else f"<div class='page'>{n}/{total}</div>"
        return f"<div class='foot z'>{self.src(s)}<div class='footrow'><div class='handle'>@lelobbyactu</div>{right}</div></div>"

    def bg(self, h, op, pos="center top"):
        return (f"<img class='bgimg' src='{self.img}' style='height:{h}%;opacity:{op};object-position:{pos}'>"
                f"<div class='bgfade' style='background:linear-gradient(180deg,rgba(17,17,20,.35) 0%,rgba(17,17,20,.15) {h*0.4:.0f}%,{BG} {h}%,{BG} 100%)'></div>")

    @staticmethod
    def head(s, size=60):
        k = f"<div class='kicker'>{fmt(s.get('kicker'))}</div>" if s.get("kicker") else ""
        return f"<div style='margin-top:90px'>{k}<div class='h' style='font-size:{s.get('title_size', size)}px;margin-top:22px'>{fmt(s['title'], True)}</div></div>"

    @staticmethod
    def extras(s):
        out = ""
        if s.get("note"):
            out += f"<div class='card' style='margin-top:40px'><div class='lbl'>{fmt(s['note'])}</div></div>"
        if s.get("avis"):
            out += (f"<div class='cta' style='margin-top:{12 if s.get('note') else 36}px'><div class='kicker' style='color:{BG}'>Notre avis</div>"
                    f"<div class='h' style='margin-top:10px'>{fmt(s['avis'])}</div></div>")
        return out

    # --- types ---
    def cover(self, s, n, t):
        return (f"<div class='slide'>{self.bg(52, .55, s.get('image_pos', 'center top'))}{self.top(True)}"
                f"<div class='z' style='margin-top:{s.get('title_top', 560)}px'><div class='h' style='font-size:{s.get('title_size', 84)}px'>{fmt(s['title'], True)}</div>"
                f"<div class='sub' style='margin-top:36px;max-width:900px'>{fmt(s.get('sub'))}</div></div>"
                f"{self.foot(s.get('source') or ['Image', self.credit], n, t, swipe=True)}</div>")

    def split(self, s, n, t):
        L, R, sh = s["left"], s["right"], int(s.get("share", 70))
        return (f"<div class='slide'>{self.top()}{self.head(s, 64)}"
                f"<div style='margin-top:64px;display:flex;height:120px;border-radius:12px;overflow:hidden'>"
                f"<div style='width:{sh}%;background:{Y};color:{BG};display:flex;align-items:center;padding-left:28px' class='h'><span style='font-size:36px'>{fmt(L.get('short', ''))}</span></div>"
                f"<div style='width:{100-sh}%;background:#3A3A42;display:flex;align-items:center;justify-content:center' class='h'><span style='font-size:28px'>{fmt(R.get('short', ''))}</span></div></div>"
                f"<div style='display:flex;gap:40px;margin-top:40px'>"
                f"<div style='flex:3'><div class='big y' style='font-size:88px'>{fmt(L['value'])}</div><div class='lbl' style='margin-top:12px'>{fmt(L['label'])}</div></div>"
                f"<div style='flex:2'><div class='big' style='font-size:88px'>{fmt(R['value'])}</div><div class='lbl' style='margin-top:12px'>{fmt(R['label'])}</div></div></div>"
                f"{self.extras(s)}{self.foot(s.get('source'), n, t)}</div>")

    def bars(self, s, n, t):
        mx = max(float(b["num"]) for b in s["bars"]) or 1
        rows = ""
        for b in s["bars"]:
            w = max(4, 72 * float(b["num"]) / mx)
            col, cls = (Y, "y") if b.get("hot") else ("#3A3A42", "")
            rows += (f"<div style='margin-top:34px'><div class='lbl' style='margin-bottom:12px'>{fmt(b['label'])}</div>"
                     f"<div style='display:flex;align-items:center;gap:24px'><div style='height:92px;width:{w:.1f}%;border-radius:8px;background:{col}'></div>"
                     f"<div class='{cls}' style='font-family:Unbounded;font-weight:800;font-size:40px;white-space:nowrap'>{fmt(b['value'])}</div></div></div>")
        return f"<div class='slide'>{self.top()}{self.head(s, 62)}<div style='margin-top:30px'>{rows}</div>{self.extras(s)}{self.foot(s.get('source'), n, t)}</div>"

    def versus(self, s, n, t):
        def col(c, hot):
            border = f"border:3px solid {Y};" if hot else ""
            return (f"<div class='box' style='flex:1;{border}'><div class='kicker' style='{'color:' + Y if hot else ''}'>{fmt(c.get('kicker'))}</div>"
                    f"<div class='big {'y' if hot else ''}' style='font-size:{c.get('size', 64)}px;margin-top:18px'>{fmt(c['value'])}</div>"
                    f"<div class='lbl' style='margin-top:14px'>{fmt(c['label'])}</div></div>")
        return (f"<div class='slide'>{self.top()}{self.head(s, 60)}<div style='display:flex;gap:28px;margin-top:48px'>"
                f"{col(s['left'], False)}{col(s['right'], True)}</div>{self.extras(s)}{self.foot(s.get('source'), n, t)}</div>")

    def cards(self, s, n, t):
        cs = s["cards"]
        size = s.get("value_size", 72 if len(cs) <= 2 else 54)
        items = ""
        for i, c in enumerate(cs):
            tg = (f"<div class='tag' style='background:{c.get('tag_color', '#3A3A42')};color:{c.get('tag_fg', '#fff')};font-size:20px;margin-bottom:22px'>{fmt(c['tag'])}</div><br>"
                  if c.get("tag") else "")
            items += (f"<div class='box' style='flex:1'>{tg}<div class='big {'y' if i == 0 and c.get('hot', True) else ''}' style='font-size:{size}px'>{fmt(c['value'])}</div>"
                      + (f"<div class='lbl' style='margin-top:14px'>{fmt(c.get('label'))}</div>" if c.get("label") else "") + "</div>")
        text = f"<div class='sub' style='margin-top:40px'>{fmt(s['text'])}</div>" if s.get("text") else ""
        return (f"<div class='slide'>{self.top()}{self.head(s, 60)}{text}<div style='display:flex;gap:18px;margin-top:50px'>{items}</div>"
                f"{self.extras(s)}{self.foot(s.get('source'), n, t)}</div>")

    def text(self, s, n, t):
        return (f"<div class='slide'>{self.top()}{self.head(s, 60)}<div class='sub' style='margin-top:44px'>{fmt(s['text'])}</div>"
                f"{self.extras(s)}{self.foot(s.get('source'), n, t)}</div>")

    def subscribe(self, s, n, t):
        return (f"<div class='slide'>{self.bg(62, .42)}<div class='top z'><div class='logo'>LE<br>LOBBY</div></div>"
                f"<div class='z' style='margin-top:auto'><div class='h' style='font-size:96px;white-space:nowrap'><span class='hl'>Abonne-toi</span></div>"
                f"<div class='sub' style='margin-top:44px;max-width:820px'>{fmt(s.get('line', 'Chaque jour, l’actu gaming et créateurs qui compte.'))}</div>"
                f"<div class='handle' style='font-size:44px;padding:16px 32px;border-width:4px;margin-top:48px'>@lelobbyactu</div></div>"
                f"<div class='footrow z' style='margin-top:56px'>{self.src(['Image', self.credit])}<div class='page'>{n}/{t}</div></div></div>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    a = ap.parse_args()
    spec = json.loads(pathlib.Path(a.spec).read_text(encoding="utf-8"))
    post = spec["post"]
    out = ROOT / "posts" / post
    out.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path("/tmp") / f"carousel-{post}"
    shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)

    img = spec.get("image", "assets/keyart/gta6.jpg")
    if img.startswith("http"):
        dst = work / "image.jpg"
        req = urllib.request.Request(img, headers={"User-Agent": "Mozilla/5.0"})
        dst.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        spec["_image_uri"] = dst.as_uri()
    else:
        spec["_image_uri"] = (ROOT / img).resolve().as_uri()

    slides = list(spec["slides"])
    if slides[-1].get("type") != "subscribe":
        slides.append({"type": "subscribe"})
    if slides[0].get("type") != "cover":
        sys.exit("La 1re slide doit être de type cover.")
    deck = Deck(spec)
    total = len(slides)
    pages = [getattr(deck, s["type"])(s, i, total) for i, s in enumerate(slides, 1)]

    from playwright.sync_api import sync_playwright
    chrome = "/usr/bin/google-chrome" if pathlib.Path("/usr/bin/google-chrome").exists() else None
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chrome, args=["--allow-file-access-from-files"])
        pg = b.new_page(viewport={"width": 1080, "height": 1350})
        for old in out.glob(f"{post}_*.jpg"):
            old.unlink()
        for i, body in enumerate(pages, 1):
            f = work / f"s{i}.html"
            f.write_text(f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>", encoding="utf-8")
            pg.goto(f.as_uri()); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(700)
            # garde-fou : rien ne doit déborder de la slide
            over = pg.evaluate("""() => { const s=document.querySelector('.slide'); const f=s.querySelector('.foot,.footrow:last-child');
                const kids=[...s.children].filter(e=>e!==f && !e.classList.contains('bgimg') && !e.classList.contains('bgfade'));
                const bottom=Math.max(...kids.map(e=>e.getBoundingClientRect().bottom));
                const wide=[...s.querySelectorAll('*')].filter(e=>!e.classList.contains('bgimg')&&!e.classList.contains('bgfade')).some(e=>e.getBoundingClientRect().right>1080-60);
                return bottom > f.getBoundingClientRect().top + 2 || f.getBoundingClientRect().bottom > 1350 || wide }""")
            if over:
                why = pg.evaluate("""() => { const s=document.querySelector('.slide');
                    return [...s.querySelectorAll('*')].filter(e=>!e.classList.contains('bgimg')&&!e.classList.contains('bgfade')&&e.getBoundingClientRect().right>1020)
                      .map(e=>(e.textContent||'').trim().slice(0,30)).slice(0,3) }""")
                print(f"ATTENTION slide {i} : contenu qui déborde ou chevauche le pied de page, raccourcir le texte {why}", file=sys.stderr)
            png = work / f"s{i}.png"
            pg.screenshot(path=str(png))
            subprocess.run(["python3", "-c", f"from PIL import Image;Image.open('{png}').convert('RGB').save('{out / f'{post}_{i:02d}.jpg'}',quality=93)"], check=True)
        b.close()
    # planche de contrôle (non publiée) pour la relecture visuelle
    sheet = work / "planche.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-pattern_type", "glob", "-i", str(out / f"{post}_*.jpg"),
                    "-vf", f"scale=432:540,tile={total}x1", "-frames:v", "1", str(sheet)], check=False)
    print(json.dumps({"post": post, "slides": [str(out / f"{post}_{i:02d}.jpg") for i in range(1, total + 1)], "planche": str(sheet)}))


if __name__ == "__main__":
    main()
