import { get, put } from '@vercel/blob';

const STATE_PATH = 'veshudei/state.json';

function blankState() {
  return { version: 1, chatId: null, userId: null, username: null, awaiting: null, events: [], updatedAt: null };
}

export async function loadState() {
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

export async function saveState(state) {
  state.updatedAt = new Date().toISOString();
  if (Array.isArray(state.events) && state.events.length > 1500) state.events = state.events.slice(-1500);
  await put(STATE_PATH, JSON.stringify(state, null, 2), {
    access: 'private',
    allowOverwrite: true,
    addRandomSuffix: false,
    contentType: 'application/json; charset=utf-8',
    cacheControlMaxAge: 0
  });
}

export function sakhalinDay(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Sakhalin', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date);
  const m = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return m.year + '-' + m.month + '-' + m.day;
}

export function logEvent(state, type, value, meta = {}) {
  state.events.push({ ts: new Date().toISOString(), day: sakhalinDay(), type, value, ...meta });
}

export function todayEvents(state) {
  const day = sakhalinDay();
  return (state.events || []).filter((e) => e.day === day);
}

export function lastEvent(state, type) {
  const xs = (state.events || []).filter((e) => e.type === type);
  return xs.length ? xs[xs.length - 1] : null;
}
