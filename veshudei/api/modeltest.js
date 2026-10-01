import { modelText } from '../lib/model.js';

export const config = { maxDuration: 30 };

export default async function handler(req, res) {
  try {
    const result = await modelText({
      system: 'Reply in Russian with exactly: OK',
      text: 'Test',
      maxTokens: 16
    });
    return res.status(200).json({
      ok: Boolean(result?.text),
      provider: result?.provider || null,
      text: result?.text || null,
      errors: Array.isArray(result?.errors) ? result.errors : []
    });
  } catch (error) {
    return res.status(200).json({ ok: false, error: String(error?.message || error) });
  }
}
