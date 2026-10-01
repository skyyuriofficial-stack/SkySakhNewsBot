import { get, put } from '@vercel/blob';
import { randomUUID } from 'node:crypto';

const STATE_PATH = 'veshudei/state.json';

function blankState() {
  return {
    version: 2,
    chatId: null,
    userId: null,
    username: null,
    awaiting: null,
    events: [],
    processedUpdateIds: [],
    updatedAt: null
  };
}

function eventKey(e) {
  if (e?.id) return String(e.id);
  return [e?.ts || '', e?.type || '', JSON.stringify(e?.value ?? null), e?.day || ''].join('|');
}

function mergeStates(base, next) {
  const a = { ...blankState(), ...(base || {}) };
  const b = { ...blankState(), ...(next || {}) };

  const map = new Map();
  for (const e of [...(a.events || []), ...(b.events || [])]) map.set(eventKey(e), e);
  const events = [...map.values()]
    .sort((x, y) => String(x.ts || '').localeCompare(String(y.ts || '')))
    .slice(-1500);

  const processedUpdateIds = [...new Set([
    ...(a.processedUpdateIds || []),
    ...(b.processedUpdateIds || [])
  ])].slice(-250);

  return {
    ...a,
    ...b,
    version: 2,
    chatId: b.chatId ?? a.chatId,
    userId: b.userId ?? a.userId,
    username: b.username ?? a.username,
    awaiting: b.awaiting,
    events,
    processedUpdateIds
  };
}

async function readState() {
  try {
    const result = await get(STATE_PATH, { access: 'private', useCache: false });
    if (!result || result.statusCode !== 200) return blankState();
    const txt = await new Response(result.stream).text();
    return { ...blankState(), ...JSON.parse(txt) };
  } catch (error) {
    const msg = String(error?.message || error).toLowerCase();
    if (msg.includes('not found') || msg.includes('404')) return blankState();
    throw error;
  }
}

export function loadState() {
  return readState();
}

export async function saveState(state) {
  let desired = { ...blankState(), ...(state || {}) };

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const latest = await readState();
    desired = mergeStates(latest, desired);
    desired.updatedAt = new Date().toISOString();

    await put(STATE_PATH, JSON.stringify(desired, null, 2), {
      access: 'private',
      allowOverwrite: true,
      addRandomSuffix: false,
      contentType: 'application/json; charset=utf-8',
      cacheControlMaxAge: 0
    });

    if (attempt === 2) break;

    await new Promise((resolve) => setTimeout(resolve, 40 * (attempt + 1)));
    const verify = await readState();
    const verifyEvents = new Set((verify.events || []).map(eventKey));
    const wantedRecent = (desired.events || []).slice(-25);
    const eventsOk = wantedRecent.every((e) => verifyEvents.has(eventKey(e)));
    const idsOk = (desired.processedUpdateIds || []).slice(-25)
      .every((id) => (verify.processedUpdateIds || []).includes(id));

    if (eventsOk && idsOk) {
      desired = mergeStates(verify, desired);
      break;
    }
    desired = mergeStates(verify, desired);
  }

  Object.assign(state, desired);
}

export function sakhalinDay(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Sakhalin',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(date);
  const m = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return m.year + '-' + m.month + '-' + m.day;
}

export function logEvent(state, type, value, meta = {}) {
  if (!Array.isArray(state.events)) state.events = [];
  state.events.push({
    id: randomUUID(),
    ts: new Date().toISOString(),
    day: sakhalinDay(),
    type,
    value,
    ...meta
  });
}

export function todayEvents(state) {
  const day = sakhalinDay();
  return (state.events || []).filter((e) => e.day === day);
}

export function lastEvent(state, type) {
  const xs = (state.events || []).filter((e) => e.type === type);
  return xs.length ? xs[xs.length - 1] : null;
}
