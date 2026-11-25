/**
 * PortWatch VI -> Telegram (Google Apps Script)
 *
 * Checa https://portwatch-vi.xyz a cada 5 minutos e manda uma mensagem no Telegram quando a
 * porcentagem do projeto líder muda, ou quando outro projeto assume a liderança.
 *
 * Como usar (detalhes em apps_script/LEIA-ME.md):
 *   1. Preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID abaixo.
 *   2. Rode a função "instalarGatilho" uma vez (e autorize o acesso).
 *   3. Pronto. Para receber o status atual quando quiser, rode "testar".
 */

const TELEGRAM_BOT_TOKEN = 'COLE_AQUI_O_TOKEN_DO_BOT';
const TELEGRAM_CHAT_ID = 'COLE_AQUI_O_CHAT_ID';
const INTERVALO_MINUTOS = 5;          // 1, 5, 10, 15 ou 30
const AVISAR_QUANDO_SO_FPS_MUDA = false;

const BASE_URL = 'https://portwatch-vi.xyz';
const STATE_KEY = 'portwatch_state';

// ---------------------------------------------------------------------------------------
// Funções para rodar pelo editor
// ---------------------------------------------------------------------------------------

/** Cria o gatilho que roda "verificar" a cada INTERVALO_MINUTOS. Rode uma vez. */
function instalarGatilho() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'verificar')
    .forEach((t) => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('verificar').timeBased().everyMinutes(INTERVALO_MINUTOS).create();
  Logger.log('Gatilho criado: verificar() a cada ' + INTERVALO_MINUTOS + ' min.');
  verificar();
}

/** Remove o gatilho (para parar o monitor). */
function removerGatilho() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'verificar')
    .forEach((t) => ScriptApp.deleteTrigger(t));
  Logger.log('Gatilho removido.');
}

/** Manda o status atual agora, mesmo sem mudança. */
function testar() {
  checar_(true);
}

/** Chamada pelo gatilho. Só manda mensagem quando algo muda. */
function verificar() {
  checar_(false);
}

// ---------------------------------------------------------------------------------------
// Modelo de pontuação (o mesmo de https://portwatch-vi.xyz/assets/js/scoring.js)
// ---------------------------------------------------------------------------------------

const MILESTONES = [
  ['groundwork', 'Preparação', 0],
  ['loads', 'Exe rodando', 10],
  ['boots', 'Primeiro frame', 20],
  ['menu', 'Menu principal', 30],
  ['world', 'No mundo', 40],
  ['playable', 'Jogável', 50],
  ['complete', 'Completo', 100],
];
const TICK = Object.fromEntries(MILESTONES.map((m) => [m[0], m[2]]));
const MILESTONE_LABEL = Object.fromEntries(MILESTONES.map((m) => [m[0], m[1]]));
const LADDER = ['loads', 'boots', 'menu', 'world', 'playable'];
const TRACK_WEIGHTS = { story: 0.35, render: 0.25, perf: 0.2, stability: 0.2 };
const GROUNDWORK_WEIGHTS = { loader: 0.2, shaders: 0.28, graphics: 0.32, proven: 0.2 };
const STORY_STEPS = [
  [0, 'Preso no início'],
  [0.1, 'Prólogo concluído'],
  [0.25, 'Primeiras missões'],
  [0.4, 'Primeiro ato'],
  [0.6, 'Metade da história'],
  [0.85, 'História principal até os créditos'],
  [1, '100% concluído'],
];
const RENDER_STEPS = [
  [0, 'Preto ou quebrado'],
  [0.25, 'Formas desenhadas, quase sem luz ou pretas'],
  [0.5, 'Iluminado, mas faltam efeitos importantes'],
  [0.75, 'Quase igual ao console, falhas pequenas'],
  [1, 'Igual ao console'],
];
const STABILITY = {
  unknown: ['Desconhecida', 0],
  constant: ['Trava o tempo todo', 0],
  often: ['Trava com frequência', 0.25],
  sometimes: ['Trava às vezes', 0.55],
  rarely: ['Raramente trava', 0.8],
  stable: ['Estável', 1],
};

const clamp01 = (v) => (Number.isFinite(+v) ? Math.min(1, Math.max(0, +v)) : 0);

function ladderValue_(v) {
  if (v === true) return 1;
  if (v === false || v == null) return 0;
  return clamp01(v);
}

function scoreEffort_(effort) {
  const gwObj = effort.groundwork || {};
  const gw = Object.keys(GROUNDWORK_WEIGHTS).reduce((s, k) => s + GROUNDWORK_WEIGHTS[k] * clamp01(gwObj[k]), 0);
  const gta = effort.gta || {};
  let score = TICK.loads * gw;
  let reached = 'groundwork';
  let prevTick = score;

  for (const key of LADDER) {
    const v = ladderValue_(gta[key]);
    if (v >= 1) {
      score = TICK[key];
      prevTick = score;
      reached = key;
      continue;
    }
    if (v > 0) score = Math.max(score, prevTick + v * (TICK[key] - prevTick));
    break;
  }

  const tracks = {
    story: clamp01(gta.story),
    render: clamp01(gta.render),
    perf: clamp01((+gta.fps || 0) / 30),
    stability: typeof gta.stability === 'number' ? clamp01(gta.stability) : (STABILITY[gta.stability] || STABILITY.unknown)[1],
  };
  const quality = Object.keys(TRACK_WEIGHTS).reduce((s, k) => s + TRACK_WEIGHTS[k] * tracks[k], 0);
  if (reached === 'playable') {
    score = TICK.playable + quality * (TICK.complete - TICK.playable);
    if (quality >= 1) reached = 'complete';
  }
  if (Number.isFinite(effort.manualScore)) score = Math.min(100, Math.max(0, effort.manualScore));

  return { score: Math.round(score * 10) / 10, reached: reached };
}

const isPrivate_ = (e) => !(typeof e.repo === 'string' && e.repo.includes('/'));

function ranked_(efforts) {
  return efforts
    .filter((e) => !e.nuked)
    .map((e) => Object.assign({ effort: e }, scoreEffort_(e)))
    .sort((a, b) => b.score - a.score || ((b.effort.stats || {}).stars || 0) - ((a.effort.stats || {}).stars || 0));
}

// ---------------------------------------------------------------------------------------
// Mensagem
// ---------------------------------------------------------------------------------------

function stepLabel_(steps, v) {
  v = clamp01(v);
  let label = steps[0][1];
  for (const [t, l] of steps) if (v >= t) label = l;
  return label;
}

function stabilityLabel_(v) {
  if (typeof v !== 'number') return (STABILITY[v] || STABILITY.unknown)[0];
  let best = 'constant';
  for (const key of Object.keys(STABILITY)) {
    if (key === 'unknown') continue;
    if (Math.abs(STABILITY[key][1] - v) <= Math.abs(STABILITY[best][1] - v) + 1e-9) best = key;
  }
  return STABILITY[best][0];
}

const num_ = (x) => String(Math.round(x * 10) / 10);
const pct_ = (x) => num_(x) + '%';
const esc_ = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const attr_ = (s) => esc_(s).replace(/"/g, '&quot;');

function buildMessage_(tracker, ranked, prev, isTest) {
  const lead = ranked[0];
  const e = lead.effort;
  const gta = e.gta || {};
  const score = lead.score;
  const playable = lead.reached === 'playable' || lead.reached === 'complete';
  const L = [];

  if (isTest) L.push('🧪 <b>PortWatch VI: status atual</b>');
  else if (!prev) L.push('🛰 <b>PortWatch VI: monitoramento iniciado</b>');
  else if (prev.leader_id !== e.id) L.push('👑 <b>PortWatch VI: NOVO LÍDER!</b>');
  else L.push((score - prev.score > 0 ? '📈' : '📉') + ' <b>PortWatch VI: a porcentagem do líder mudou</b>');
  L.push('');

  if (prev && !isTest) {
    const diff = score - prev.score;
    const delta = '(' + (diff >= 0 ? '+' : '−') + pct_(Math.abs(diff)) + ')';
    if (prev.leader_id !== e.id) {
      L.push('<b>' + pct_(prev.score) + '</b> (' + esc_(prev.leader_name || prev.leader_id) + ') → <b>' + pct_(score) + '</b> ' + delta);
    } else {
      L.push('<b>' + pct_(prev.score) + ' → ' + pct_(score) + '</b> ' + delta);
    }
  } else {
    L.push('<b>' + pct_(score) + '</b>');
  }

  const name = e.name || e.id;
  if (!isPrivate_(e)) {
    L.push('🏆 <b>' + esc_(name) + '</b> · <a href="https://github.com/' + attr_(e.repo) + '">' + esc_(e.repo) + '</a>');
  } else {
    L.push('🏆 <b>' + esc_(name) + '</b> · versão privada (sem código público)');
  }
  const meta = [MILESTONE_LABEL[lead.reached] || lead.reached];
  if (e.approach) meta.push(e.approach);
  if (e.target) meta.push(e.target);
  const ver = { portwatch: 'Verificado pelo PortWatch', 'self-reported': 'Autodeclarado' }[e.verification];
  if (ver) meta.push(ver);
  L.push('<i>' + esc_(meta.join(' · ')) + '</i>');
  L.push('');

  if (playable) {
    L.push('📖 História: ' + esc_(stepLabel_(STORY_STEPS, gta.story)));
    L.push('🎨 Gráficos: ' + esc_(stepLabel_(RENDER_STEPS, gta.render)));
    L.push('⚡ Desempenho: <b>' + (Number.isFinite(+gta.fps) && gta.fps != null ? num_(+gta.fps) : '?') + ' FPS</b>');
    L.push('🧱 Estabilidade: ' + esc_(stabilityLabel_(gta.stability)));
    L.push('');
  }

  if (e.summary) { L.push(esc_(e.summary)); L.push(''); }
  if (e.highlights && e.highlights.length) {
    L.push('✅ <b>O que funciona</b>');
    e.highlights.forEach((h) => L.push('• ' + esc_(h)));
    L.push('');
  }
  if (e.blockers && e.blockers.length) {
    L.push('❌ <b>O que está travando</b>');
    e.blockers.forEach((b) => L.push('• ' + esc_(b)));
    L.push('');
  }
  if (e.proof && e.proof.url) {
    L.push('🎬 <a href="' + attr_(e.proof.url) + '">' + esc_(e.proof.label || 'Prova') + '</a>');
  }

  L.push('');
  L.push('<b>Top 3</b>');
  ranked.slice(0, 3).forEach((s, i) => {
    const fps = +((s.effort.gta || {}).fps);
    L.push((i + 1) + '. ' + esc_(s.effort.name || s.effort.id) + (isPrivate_(s.effort) ? ' (privada)' : '') + ': ' +
      pct_(s.score) + (fps ? ' · ' + num_(fps) + ' FPS' : ''));
  });

  L.push('');
  L.push('<a href="' + BASE_URL + '/#effort-' + attr_(e.id || '') + '">Abrir no PortWatch</a>' +
    (tracker.updated ? ' · dados de ' + esc_(tracker.updated) : ''));

  let text = L.join('\n');
  if (text.length > 4000) text = text.slice(0, 3990) + '\n…';
  return text;
}

// ---------------------------------------------------------------------------------------
// Rede / estado
// ---------------------------------------------------------------------------------------

function fetchTracker_() {
  const res = UrlFetchApp.fetch(BASE_URL + '/data/tracker.json?ts=' + Date.now(), {
    muteHttpExceptions: true,
    headers: { 'Cache-Control': 'no-cache' },
  });
  if (res.getResponseCode() !== 200) throw new Error('Site respondeu HTTP ' + res.getResponseCode());
  return JSON.parse(res.getContentText('UTF-8'));
}

function sendTelegram_(text) {
  const res = UrlFetchApp.fetch('https://api.telegram.org/bot' + TELEGRAM_BOT_TOKEN + '/sendMessage', {
    method: 'post',
    muteHttpExceptions: true,
    payload: {
      chat_id: String(TELEGRAM_CHAT_ID),
      text: text,
      parse_mode: 'HTML',
      disable_web_page_preview: 'true',
    },
  });
  if (res.getResponseCode() !== 200) {
    throw new Error('Telegram respondeu HTTP ' + res.getResponseCode() + ': ' + res.getContentText());
  }
}

function checar_(force) {
  if (TELEGRAM_BOT_TOKEN.indexOf('COLE_AQUI') === 0 || String(TELEGRAM_CHAT_ID).indexOf('COLE_AQUI') === 0) {
    throw new Error('Preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no topo do código.');
  }

  let tracker;
  try {
    tracker = fetchTracker_();
  } catch (err) {
    // Site fora do ar ou lento: tenta de novo na próxima execução, sem gerar e-mail de erro.
    Logger.log('Não consegui ler o site: ' + err);
    if (force) throw err;
    return;
  }

  const ranked = ranked_(tracker.efforts || []);
  if (!ranked.length) { Logger.log('Nenhum projeto nos dados.'); return; }

  const lead = ranked[0];
  const e = lead.effort;
  const current = {
    leader_id: e.id,
    leader_name: e.name,
    score: lead.score,
    fps: (e.gta || {}).fps == null ? null : (e.gta || {}).fps,
    checked_at: new Date().toISOString(),
  };
  const props = PropertiesService.getScriptProperties();
  const raw = props.getProperty(STATE_KEY);
  const prev = raw ? JSON.parse(raw) : null;

  let changed = !prev || prev.leader_id !== current.leader_id || Number(prev.score) !== current.score;
  if (AVISAR_QUANDO_SO_FPS_MUDA && prev && prev.leader_id === current.leader_id && prev.fps !== current.fps) changed = true;

  Logger.log('Líder: ' + current.leader_name + ' ' + pct_(current.score) +
    (prev ? ' (antes: ' + prev.leader_name + ' ' + pct_(prev.score) + ')' : ''));

  if (!changed && !force) return;

  sendTelegram_(buildMessage_(tracker, ranked, prev, force));
  Logger.log('Mensagem enviada no Telegram.');
  props.setProperty(STATE_KEY, JSON.stringify(current));
}
