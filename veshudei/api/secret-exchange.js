import { get, put, del } from '@vercel/blob';
import { createRemoteJWKSet, jwtVerify } from 'jose';
import { generateKeyPairSync, privateDecrypt, randomUUID, constants } from 'node:crypto';

export const config = { maxDuration: 30 };

const AUDIENCE = 'veshudei-secret-exchange';
const REPOSITORY = 'skyyuriofficial-stack/SkySakhNewsBot';
const JWKS = createRemoteJWKSet(new URL('https://token.actions.githubusercontent.com/.well-known/jwks'));
const SECRET_PATH = 'veshudei/secrets/openrouter.json';

async function verifyCaller(req) {
  const auth = String(req.headers.authorization || '');
  if (!auth.startsWith('Bearer ')) throw new Error('missing bearer token');
  const token = auth.slice(7);
  const { payload } = await jwtVerify(token, JWKS, {
    issuer: 'https://token.actions.githubusercontent.com',
    audience: AUDIENCE
  });
  if (payload.repository !== REPOSITORY) throw new Error('wrong repository');
  if (payload.ref !== 'refs/heads/main') throw new Error('wrong ref');
  if (!payload.run_id) throw new Error('missing run_id');
  return payload;
}

async function readPrivate(path) {
  try {
    const result = await get(path, { access: 'private', useCache: false });
    if (!result || result.statusCode !== 200) return null;
    return await new Response(result.stream).text();
  } catch (_) {
    return null;
  }
}

async function configured() {
  const raw = await readPrivate(SECRET_PATH);
  if (!raw) return false;
  try {
    const cfg = JSON.parse(raw);
    return Boolean(cfg?.key);
  } catch (_) {
    return false;
  }
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ ok: false });

  try {
    const caller = await verifyCaller(req);
    const action = String(req.body?.action || '');

    if (action === 'status') {
      return res.status(200).json({ ok: true, configured: await configured() });
    }

    if (action === 'init') {
      if (await configured()) return res.status(200).json({ ok: true, configured: true });

      const exchangeId = randomUUID();
      const { publicKey, privateKey } = generateKeyPairSync('rsa', {
        modulusLength: 2048,
        publicKeyEncoding: { type: 'spki', format: 'pem' },
        privateKeyEncoding: { type: 'pkcs8', format: 'pem' }
      });

      const exchange = {
        privateKey,
        runId: String(caller.run_id),
        expiresAt: Date.now() + 10 * 60 * 1000
      };
      await put('veshudei/exchange/' + exchangeId + '.json', JSON.stringify(exchange), {
        access: 'private',
        allowOverwrite: true,
        addRandomSuffix: false,
        contentType: 'application/json; charset=utf-8',
        cacheControlMaxAge: 0
      });

      return res.status(200).json({
        ok: true,
        configured: false,
        exchangeId,
        publicKey
      });
    }

    if (action === 'complete') {
      const exchangeId = String(req.body?.exchangeId || '');
      const ciphertext = String(req.body?.ciphertext || '');
      if (!/^[0-9a-f-]{20,}$/i.test(exchangeId) || !ciphertext) throw new Error('invalid exchange payload');

      const exchangePath = 'veshudei/exchange/' + exchangeId + '.json';
      const raw = await readPrivate(exchangePath);
      if (!raw) throw new Error('exchange not found');
      const exchange = JSON.parse(raw);
      if (String(exchange.runId) !== String(caller.run_id)) throw new Error('run mismatch');
      if (!exchange.expiresAt || Date.now() > Number(exchange.expiresAt)) throw new Error('exchange expired');

      const plaintext = privateDecrypt({
        key: exchange.privateKey,
        padding: constants.RSA_PKCS1_OAEP_PADDING,
        oaepHash: 'sha256'
      }, Buffer.from(ciphertext, 'base64')).toString('utf8');

      const cfg = JSON.parse(plaintext);
      const key = String(cfg?.key || '');
      if (!key.startsWith('sk-or-') || key.length < 30 || key.length > 300) throw new Error('invalid OpenRouter key');

      const stored = {
        key,
        model: cfg?.model ? String(cfg.model).slice(0, 120) : null,
        visionModel: cfg?.visionModel ? String(cfg.visionModel).slice(0, 120) : 'google/gemini-2.5-flash',
        updatedAt: new Date().toISOString(),
        source: 'github-actions-oidc'
      };

      await put(SECRET_PATH, JSON.stringify(stored), {
        access: 'private',
        allowOverwrite: true,
        addRandomSuffix: false,
        contentType: 'application/json; charset=utf-8',
        cacheControlMaxAge: 0
      });
      try { await del(exchangePath); } catch (_) {}

      return res.status(200).json({ ok: true, configured: true });
    }

    return res.status(400).json({ ok: false, error: 'unknown action' });
  } catch (error) {
    console.error('secret-exchange:', error?.message || error);
    return res.status(401).json({ ok: false, error: 'unauthorized-or-invalid' });
  }
}
