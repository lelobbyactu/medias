// Le Lobby — Worker Cloudflare : reçoit les clics Telegram d'Alix et déclenche les workflows GitHub.
// Aucune clé dans le code : TELEGRAM_BOT_TOKEN et GH_DISPATCH_TOKEN sont des secrets du Worker.
const REPO = "lelobbyactu/medias";
const RAISONS = ["Sujet", "Titre", "Clip", "Montage", "Déjà vu"];

async function sha256(s) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return r.json();
}

function github(env, path, init = {}) {
  return fetch(`https://api.github.com/repos/${REPO}/${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`, "User-Agent": "lelobby-worker",
      "X-GitHub-Api-Version": "2022-11-28", Accept: "application/vnd.github+json", ...(init.headers || {}),
    },
  });
}

async function dispatch(env, workflow, inputs) {
  const r = await github(env, `actions/workflows/${workflow}/dispatches`, {
    method: "POST", body: JSON.stringify({ ref: "main", inputs }),
  });
  return r.status === 204 ? null : `GitHub a répondu ${r.status}`;
}

async function findPost(env, n) {
  const r = await github(env, "contents/state/published.json?ref=main", {
    headers: { Accept: "application/vnd.github.raw+json" },
  });
  if (!r.ok) return null;
  const j = await r.json();
  return j.posts.filter((p) => p.id.startsWith(`${n}-`)).pop() || null;
}

const keyboard = (rows) => ({ inline_keyboard: rows });
const btn = (text, data) => ({ text, callback_data: data });
const baseRows = (n) => [[btn("✅ Poster", `ok:${n}`), btn("❌ Non", `non:${n}`)],
  [btn("✏️ Autre titre", `alt:${n}`), btn("🔧 Retoucher", `retoucher:${n}`)]];
const retoucheRows = (n) => [[btn("🔍 Moins zoomé", `zoom:${n}`), btn("📐 Format 16:9", `m:${n}:16x9`)],
  [btn("✂️ Début −2 s", `m:${n}:debut`), btn("✂️ Fin −2 s", `m:${n}:fin`)],
  [btn("✍️ Autre retouche", `autre:${n}`), btn("↩︎ Retour", `retour:${n}`)]];
const zoomRows = (n) => [[btn("Webcam", `m:${n}:cam`), btn("Gameplay", `m:${n}:jeu`), btn("Les deux", `m:${n}:deux`)],
  [btn("↩︎ Retour", `retoucher:${n}`)]];

async function decide(env, chat, n, action, valeur = "") {
  const err = await dispatch(env, "decision.yml", { numero: n, action, valeur });
  if (err) await tg(env, "sendMessage", { chat_id: chat, text: `⚠️ #${n} : décision non transmise (${err}). Réessaie.` });
  return !err;
}

async function onClick(env, q) {
  const chat = q.message.chat.id, mid = q.message.message_id;
  const [action, n, arg] = (q.data || "").split(":");
  const answer = (text) => tg(env, "answerCallbackQuery", { callback_query_id: q.id, text });
  const buttons = (rows) => tg(env, "editMessageReplyMarkup", { chat_id: chat, message_id: mid, reply_markup: keyboard(rows) });
  if (!/^\d{4}$/.test(n || "")) return answer("Bouton inconnu");

  if (action === "ok" || action === "annuler") {
    await answer(action === "ok" ? "Validé, j'enregistre…" : "J'annule…");
    if (await decide(env, chat, n, action)) await buttons([]);
  } else if (action === "non") {
    await answer("Pourquoi ?");
    const rows = [];
    for (let i = 0; i < RAISONS.length; i += 3) rows.push(RAISONS.slice(i, i + 3).map((r, k) => btn(r, `r:${n}:${i + k}`)));
    rows.push([btn("✍️ Autre raison", `libre:${n}`), btn("↩︎ Retour", `retour:${n}`)]);
    await buttons(rows);
  } else if (action === "r") {
    await answer("Écarté");
    if (await decide(env, chat, n, "non", RAISONS[Number(arg)] || "sans raison")) await buttons([]);
  } else if (action === "libre") {
    await answer("");
    await tg(env, "sendMessage", { chat_id: chat, text: `#${n} · raison\nRéponds à ce message avec la raison, en un mot ou deux.`,
      reply_markup: { force_reply: true } });
  } else if (action === "alt") {
    const post = await findPost(env, n);
    if (!post || post.status !== "a_valider") return answer("Plus modifiable");
    await answer("Choisis un titre");
    const rows = (post.titres_alt || []).map((t, i) => [btn(t.replace(/\|/g, " ").replace(/\*/g, ""), `t:${n}:${i}`)]);
    rows.push([btn("✍️ Écrire le mien", `perso:${n}`), btn("↩︎ Retour", `retour:${n}`)]);
    await buttons(rows);
  } else if (action === "t") {
    const post = await findPost(env, n);
    const titre = post && (post.titres_alt || [])[Number(arg)];
    if (!titre) return answer("Titre introuvable");
    await answer("Je refais la vidéo (2-3 min)");
    if (await decide(env, chat, n, "titre", titre)) await buttons([]);
  } else if (action === "perso") {
    await answer("");
    await tg(env, "sendMessage", { chat_id: chat,
      text: `#${n} · titre\nRéponds à ce message avec ton titre. Entoure d'*étoiles* le mot à surligner. « | » force un retour à la ligne.`,
      reply_markup: { force_reply: true } });
  } else if (action === "retoucher" || action === "zoom") {
    await answer("");
    await buttons(action === "zoom" ? zoomRows(n) : retoucheRows(n));
  } else if (action === "m") {
    await answer("Je refais la vidéo (3-5 min)");
    if (await decide(env, chat, n, "retouche", arg)) {
      await buttons([]);
      await tg(env, "sendMessage", { chat_id: chat, text: `#${n} : retouche lancée, la nouvelle version arrive dans 3 à 5 min.` });
    }
  } else if (action === "autre") {
    await answer("");
    await tg(env, "sendMessage", { chat_id: chat,
      text: `#${n} · retouche\nRéponds à ce message : que faut-il changer ? (fait à la prochaine session de production)`,
      reply_markup: { force_reply: true } });
  } else if (action === "retour") {
    await answer("");
    await buttons(baseRows(n));
  } else await answer("Bouton inconnu");
}

// envoie les vidéos montées avant que le bot soit relié (ou dont l'envoi a échoué)
async function sendPending(env, chat) {
  const err = await dispatch(env, "telegram.yml", {});
  if (err) await tg(env, "sendMessage", { chat_id: chat, text: `⚠️ Envoi des vidéos non lancé (${err}).` });
}

async function onMessage(env, m) {
  const chat = m.chat.id, text = (m.text || "").trim();
  const owner = await env.KV.get("owner");
  if (!owner) {
    // premier /start en conversation privée = propriétaire (bot neuf, connu du seul Alix)
    if (m.chat.type !== "private" || !text.startsWith("/start")) return;
    await env.KV.put("owner", String(chat));
    await tg(env, "sendMessage", { chat_id: chat, text: "✅ Bot relié à cette conversation. Les vidéos du Lobby arriveront ici." });
    return sendPending(env, chat);
  }
  if (String(chat) !== owner) return;
  if (text.startsWith("/start")) {
    await tg(env, "sendMessage", { chat_id: chat, text: "Bot prêt. J'envoie les vidéos en attente, s'il y en a." });
    return sendPending(env, chat);
  }
  const reply = m.reply_to_message && (m.reply_to_message.text || "").match(/^#(\d{4}) · (titre|raison|retouche)/);
  if (reply && text) {
    const [, n, kind] = reply;
    const action = { titre: "titre", raison: "non", retouche: "autre" }[kind];
    if (await decide(env, chat, n, action, text.slice(0, 300)) && kind !== "retouche")
      await tg(env, "sendMessage", { chat_id: chat, text: kind === "titre" ? `#${n} : je refais la vidéo (2-3 min).` : `#${n} : noté.` });
    return;
  }
  await tg(env, "sendMessage", { chat_id: chat, text: "Bot prêt. Utilise les boutons sous les vidéos." });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/chat") {
      // lu par GitHub Actions pour savoir où envoyer les vidéos
      const key = await sha256(`${env.TELEGRAM_BOT_TOKEN}:api`);
      if (request.headers.get("Authorization") !== `Bearer ${key}`) return new Response("non", { status: 401 });
      return Response.json({ chat_id: await env.KV.get("owner") });
    }
    if (request.method !== "POST" || url.pathname !== "/telegram") return new Response("Le Lobby", { status: 200 });
    const secret = await sha256(`${env.TELEGRAM_BOT_TOKEN}:webhook`);
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== secret) return new Response("non", { status: 401 });
    try {
      const u = await request.json();
      if (u.callback_query) {
        const owner = await env.KV.get("owner");
        if (owner && String(u.callback_query.message?.chat?.id) === owner) await onClick(env, u.callback_query);
      } else if (u.message) await onMessage(env, u.message);
    } catch (e) {
      console.log("erreur", e.message);
    }
    return new Response("ok");
  },

  // Cron toutes les heures : publication aux créneaux (heure de Paris, changement d'heure géré)
  async scheduled(event, env) {
    const h = Number(new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", hourCycle: "h23", timeZone: "Europe/Paris" })
      .format(new Date(event.scheduledTime)).slice(0, 2));
    // créneaux + un passage une heure après, pour confirmer les posts urgents et rattraper une publication interrompue
    const controle = [9, 13, 19, 22].includes(h);   // contrôle seulement : jamais un 2e post
    if (controle || [8, 12, 18, 21].includes(h)) {
      const err = await dispatch(env, "publish.yml", { mode: controle ? "confirmer" : "publier" });
      if (err) {
        const owner = await env.KV.get("owner");
        if (owner) await tg(env, "sendMessage", { chat_id: owner, text: `⚠️ Créneau ${h} h : publication non lancée (${err}).` });
      }
    }
  },
};
