#!/usr/bin/env python3
"""Le Lobby — sous-titres automatiques des clips (DA v0.6), utilisés par make_reel_916.py.

Règles d'Alix (22 nov. 2026) : police de la DA (Unbounded), assez gros mais pas trop, gros mots masqués sauf la
1re lettre (« P***** »), mots toujours entiers (jamais coupés en fin de ligne).
Style : une seule ligne en majuscules, blanc avec contour noir, le mot prononcé en jaune DA (#F2FF3D), dans la bande
noire entre la webcam et le gameplay (milieu de l'écran).

Transcription : faster-whisper, modèle large-v3-turbo (CPU, ~7 s pour 30 s de clip ; ~1,6 Go téléchargés depuis
Hugging Face au premier appel d'une exécution).
Usage seul (test) : python3 scripts/subtitles.py clip.mp4 [--start S --end E] → affiche le texte et écrit /tmp/subs.ass
"""
import argparse, json, pathlib, re, subprocess, sys

FONTS = pathlib.Path(__file__).resolve().parent / "fonts"
TTF = FONTS / "Unbounded-ExtraBold.ttf"
FONT_NAME = "Unbounded ExtraBold"
SIZE = 58                   # « assez gros mais pas trop », puis « un peu plus imposant » (Alix, 23 nov.)
MAX_W = 1000                # largeur max d'une ligne (px, écran 1080 : 40 px de marge de chaque côté)
MAX_WORDS = 5
MAX_DUR = 2.4               # durée max d'un bloc (s)
PAUSE = 0.55                # une pause plus longue coupe le bloc
MODEL = "large-v3-turbo"

# gros mots : début de mot (minuscules, sans accents gênants) ; « con » etc. seulement en mot entier
SWEAR_PREFIX = ("putain", "merd", "bordel", "connard", "connass", "salop", "encul", "nique", "niqu", "couill",
                "foutr", "batard", "bâtard", "enfoir", "pétasse", "petasse", "chiotte", "emmerd", "fdp", "ntm")
SWEAR_EXACT = {"con", "cons", "conne", "connes", "pute", "putes", "bite", "bites", "chier", "chie", "chié", "pd",
               "nik", "niker", "tg", "ptn", "fuck", "fucking", "shit", "bitch"}
EN_WORDS = {"the", "i", "am", "you", "is", "are", "not", "what", "whatever", "happens", "in", "of", "to", "and", "it",
            "this", "that", "my", "we", "go", "yeah", "okay", "hey", "come", "on", "get", "let's", "do", "don't", "know",
            "with", "for", "be", "was", "your", "me", "he", "she", "they", "out", "here", "there", "now", "just", "all"}
FR_WORDS = {"le", "la", "les", "de", "des", "un", "une", "et", "je", "tu", "il", "on", "ça", "pas", "c'est", "mais",
            "est", "que", "qui", "les", "gars", "quoi", "non", "oui", "en", "du", "au", "à", "mon", "ma", "là", "comme"}
# mots sur lesquels une ligne ne doit pas finir (ils passent au bloc suivant)
WEAK_END = {"le", "la", "les", "l'", "de", "des", "du", "d'", "un", "une", "à", "au", "aux", "et", "mais", "ou", "je",
            "tu", "il", "elle", "on", "nous", "vous", "ils", "mon", "ma", "mes", "ton", "ta", "son", "sa", "ce", "cette",
            "pour", "avec", "dans", "sur", "en", "que", "qui", "pas", "ne", "plus", "très", "trop"}
HALLUCINATIONS = ("sous-titres réalisés", "amara.org", "merci d'avoir regardé", "sous-titrage", "abonnez-vous",
                  "st' 501", "société radio-canada")


def censor(word):
    core = re.sub(r"[^\wÀ-ÿ'-]", "", word)
    low = core.lower()
    base = low.split("'")[-1]  # « l'enculé » → « enculé »
    if not base:
        return word
    if base in SWEAR_EXACT or any(base.startswith(p) for p in SWEAR_PREFIX):
        start = len(core) - len(base)
        return word.replace(core, core[:start + 1] + "*" * (len(base) - 1))
    return word


def transcribe(video, start, length):
    import numpy as np
    try:
        from faster_whisper import WhisperModel
    except ImportError:  # environnement neuf d'une tâche planifiée
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", "faster-whisper"],
                       check=True, capture_output=True)
        from faster_whisper import WhisperModel
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(video),
                          "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True).stdout
    audio = np.frombuffer(raw, np.float32)
    if audio.size < 16000:
        return []
    m = WhisperModel(MODEL, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(audio, language="fr", word_timestamps=True, vad_filter=True, beam_size=5,
                           condition_on_previous_text=False, temperature=0.0)
    words = []
    for s in segs:
        if any(h in s.text.lower() for h in HALLUCINATIONS):
            continue
        toks = [re.sub(r"[^\w'’]", "", w.word.strip().lower()) for w in s.words]
        en = sum(t in EN_WORDS for t in toks); fr = sum(t in FR_WORDS for t in toks)
        if toks and en >= max(2, 0.4 * len(toks)) and en > fr:   # dialogue anglais du jeu : pas le streamer
            continue
        for w in s.words:
            t = w.word.strip()
            if not t:
                continue
            # Whisper coupe « c'est » en « c » + « 'est », « dites-moi » en « Dites » + « -moi » : on recolle
            if words and (t[0] in "'’-" or words[-1][2].endswith(("'", "’")) or not any(c.isalnum() for c in t)):
                sep = " " if t[0] in "?!:;" else ""   # « Non ? » (typographie française)
                words[-1] = (words[-1][0], w.end, words[-1][2] + sep + t, min(words[-1][3], w.probability))
            else:
                words.append((w.start, w.end, t, w.probability))
    return [w for w in words if w[3] >= 0.25]


def save_words(words, path):
    """Mots horodatés (relisibles et corrigeables : ne changer que le champ « mot »)."""
    pathlib.Path(path).write_text(json.dumps([{"debut": round(w[0], 2), "fin": round(w[1], 2), "mot": w[2],
                                               "confiance": round(w[3], 2)} for w in words], ensure_ascii=False, indent=0),
                                  encoding="utf-8")


def load_words(path):
    return [(d["debut"], d["fin"], d["mot"], d.get("confiance", 1.0))
            for d in json.loads(pathlib.Path(path).read_text(encoding="utf-8")) if d["mot"].strip()]


def chunks(words):
    from PIL import ImageFont
    font = ImageFont.truetype(str(TTF), SIZE)
    width = lambda txt: font.getlength(txt.upper())
    out, cur = [], []
    for w in words:
        if cur:
            text = " ".join(censor(x[2]) for x in cur + [w])
            too_long = width(text) > MAX_W or len(cur) >= MAX_WORDS or w[1] - cur[0][0] > MAX_DUR
            pause = w[0] - cur[-1][1] > PAUSE
            ends = cur[-1][2].endswith((".", "?", "!", "…"))
            if too_long or pause or ends:
                carry = []
                if too_long and not (pause or ends):   # ne pas finir une ligne sur « des », « la », « je »…
                    while len(cur) > 1 and re.sub(r"[^\w'’]", "", cur[-1][2].lower()) in WEAK_END:
                        carry.insert(0, cur.pop())
                out.append(cur); cur = carry
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def ts(t):
    t = max(0.0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(words, path, y, total):
    blocks = chunks(words)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{FONT_NAME},{SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,4,2,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for bi, b in enumerate(blocks):
        nxt = blocks[bi + 1][0][0] if bi + 1 < len(blocks) else total
        b_end = min(nxt, b[-1][1] + 0.6)
        for i, w in enumerate(b):
            st = w[0] if i else b[0][0]
            en = b[i + 1][0] if i + 1 < len(b) else b_end
            parts = []
            for j, x in enumerate(b):
                t = censor(x[2]).upper().replace("{", "(").replace("}", ")")
                parts.append("{\\c&H3DFFF2&}" + t + "{\\c&HFFFFFF&}" if j == i else t)
            pop = "{\\fscx88\\fscy88\\t(0,90,\\fscx100\\fscy100)}" if i == 0 else ""
            ev.append(f"Dialogue: 0,{ts(st)},{ts(en)},Sub,,0,0,0,,{{\\pos(540,{y})}}{pop}" + " ".join(parts))
    pathlib.Path(path).write_text(head + "\n".join(ev) + "\n", encoding="utf-8")
    return blocks


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("--start", type=float, default=0); ap.add_argument("--end", type=float, default=None)
    a = ap.parse_args()
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.video],
                               capture_output=True, text=True).stdout)
    end = a.end if a.end is not None else dur
    w = transcribe(a.video, a.start, end - a.start)
    b = write_ass(w, "/tmp/subs.ass", 940, end - a.start)
    print(" | ".join(" ".join(censor(x[2]) for x in blk) for blk in b))
