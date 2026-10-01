import { createRemoteJWKSet, jwtVerify } from 'jose';
import {
  createProviderExchange,
  completeProviderExchange,
  providerConfigured
} from '../lib/provider-secret.js';

export const config = { maxDuration: 30 };

const AUDIENCE = 'veshudei-secret-exchange';
const REPOSITORY = 'skyyuriofficial-stack/SkySakhNewsBot';
const JWKS = createRemoteJWKSet(new URL('https://token.actions.githubusercontent.com/.well-known/jwks'));

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

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ ok: false });

  try {
    const caller = await verifyCaller(req);
    const action = String(req.body?.action || '');

    if (action === 'status') {
      return res.status(200).json({ ok: true, configured: await providerConfigured() });
    }

    if (action === 'init') {
      const result = await createProviderExchange(caller.run_id);
      return res.status(200).json({ ok: true, ...result });
    }

    if (action === 'complete') {
      const result = await completeProviderExchange(
        String(req.body?.exchangeId || ''),
        String(req.body?.ciphertext || ''),
        caller.run_id
      );
      return res.status(200).json({
        ok: true,
        configured: Boolean(result?.key),
        model: result?.model || null,
        visionModel: result?.visionModel || null
      });
    }

    return res.status(400).json({ ok: false, error: 'unknown action' });
  } catch (error) {
    console.error('secret-exchange:', error?.message || error);
    return res.status(401).json({ ok: false, error: 'unauthorized-or-invalid' });
  }
}
