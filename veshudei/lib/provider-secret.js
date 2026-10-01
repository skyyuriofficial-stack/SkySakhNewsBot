import { get, put, del } from '@vercel/blob';
import { generateKeyPairSync, privateDecrypt, randomUUID, constants } from 'node:crypto';

const SECRET_PATH = 'veshudei/secrets/openrouter.json';
const EXCHANGE_PREFIX = 'veshudei/exchange/';
const INBOX_URL = 'https://raw.githubusercontent.com/skyyuriofficial-stack/SkySakhNewsBot/main/veshudei/exchange/inbox.json';

async function readPrivate(path) {
  try {
    const result = await get(path, { access: 'private', useCache: false });
    if (!result || result.statusCode !== 200) return null;
    return await new Response(result.stream).text();
  } catch (_) {
    return null;
  }
}

function normalizeConfig(cfg) {
  const key = String(cfg?.key || '');
  if (!key.startsWith('sk-or-') || key.length < 30 || key.length > 300) return null;
  return {
    key,
    model: cfg?.model ? String(cfg.model).slice(0, 120) : 'google/gemini-2.5-flash',
    visionModel: cfg?.visionModel ? String(cfg.visionModel).slice(0, 120) : 'google/gemini-2.5-flash',
    updatedAt: cfg?.updatedAt || new Date().toISOString(),
    source: cfg?.source || 'secure-exchange'
  };
}

export async function readOpenRouterConfig() {
  const raw = await readPrivate(SECRET_PATH);
  if (!raw) return null;
  try { return normalizeConfig(JSON.parse(raw)); } catch (_) { return null; }
}

export async function providerConfigured() {
  if (process.env.OPENROUTER_API_KEY) return true;
  return Boolean(await readOpenRouterConfig());
}

async function storeConfig(cfg) {
  const normalized = normalizeConfig(cfg);
  if (!normalized) throw new Error('invalid OpenRouter config');
  await put(SECRET_PATH, JSON.stringify(normalized), {
    access: 'private',
    allowOverwrite: true,
    addRandomSuffix: false,
    contentType: 'application/json; charset=utf-8',
    cacheControlMaxAge: 0
  });
  return normalized;
}

export async function createProviderExchange(runId) {
  if (await providerConfigured()) return { configured: true };

  const exchangeId = randomUUID();
  const pair = generateKeyPairSync('rsa', {
    modulusLength: 2048,
    publicKeyEncoding: { type: 'spki', format: 'pem' },
    privateKeyEncoding: { type: 'pkcs8', format: 'pem' }
  });

  await put(EXCHANGE_PREFIX + exchangeId + '.json', JSON.stringify({
    privateKey: pair.privateKey,
    runId: String(runId),
    expiresAt: Date.now() + 30 * 60 * 1000
  }), {
    access: 'private',
    allowOverwrite: true,
    addRandomSuffix: false,
    contentType: 'application/json; charset=utf-8',
    cacheControlMaxAge: 0
  });

  return { configured: false, exchangeId, publicKey: pair.publicKey };
}

export async function completeProviderExchange(exchangeId, ciphertext, runId) {
  if (!/^[0-9a-f-]{20,}$/i.test(String(exchangeId || ''))) throw new Error('invalid exchange id');
  if (!ciphertext) throw new Error('missing ciphertext');

  const exchangePath = EXCHANGE_PREFIX + exchangeId + '.json';
  const raw = await readPrivate(exchangePath);
  if (!raw) throw new Error('exchange not found');

  const exchange = JSON.parse(raw);
  if (String(exchange.runId) !== String(runId)) throw new Error('run mismatch');
  if (!exchange.expiresAt || Date.now() > Number(exchange.expiresAt)) throw new Error('exchange expired');

  const plaintext = privateDecrypt({
    key: exchange.privateKey,
    padding: constants.RSA_PKCS1_OAEP_PADDING,
    oaepHash: 'sha256'
  }, Buffer.from(String(ciphertext), 'base64')).toString('utf8');

  const cfg = JSON.parse(plaintext);
  const stored = await storeConfig({
    ...cfg,
    updatedAt: new Date().toISOString(),
    source: 'github-actions-oidc'
  });

  try { await del(exchangePath); } catch (_) {}
  return stored;
}

export async function consumeProviderInbox() {
  if (await providerConfigured()) return true;

  try {
    const response = await fetch(INBOX_URL + '?v=' + Date.now(), {
      headers: { accept: 'application/json' },
      cache: 'no-store'
    });
    if (!response.ok) return false;
    const inbox = await response.json();
    if (!inbox?.exchangeId || !inbox?.ciphertext || !inbox?.runId) return false;
    await completeProviderExchange(inbox.exchangeId, inbox.ciphertext, inbox.runId);
    return true;
  } catch (error) {
    console.error('provider inbox:', error?.message || error);
    return false;
  }
}
