import { readOpenRouterConfig, consumeProviderInbox } from './provider-secret.js';
import { get, put } from '@vercel/blob';

function dataUrl(bytes, mimeType) {
  return 'data:' + (mimeType || 'image/jpeg') + ';base64,' + Buffer.from(bytes).toString('base64');
}

function extractOpenAIResponseText(data) {
  if (typeof data?.output_text === 'string' && data.output_text.trim()) return data.output_text.trim();
  const chunks = [];
  for (const item of data?.output || []) {
    for (const part of item?.content || []) {
      if (typeof part?.text === 'string') chunks.push(part.text);
    }
  }
  return chunks.join('\n').trim();
}

let openRouterCache = null;
let openRouterCacheAt = 0;

const AI_BUDGET_PATH = 'veshudei/ai-budget.json';
const FREE_CREDIT_RESERVE_USD = Number(process.env.VESH_AI_FREE_CREDIT_RESERVE_USD || 1.00);
const DAILY_AI_CALL_LIMIT = Number(process.env.VESH_AI_DAILY_CALL_LIMIT || 25);
const MONTHLY_AI_CALL_LIMIT = Number(process.env.VESH_AI_MONTHLY_CALL_LIMIT || 300);

function dayKey() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Sakhalin',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(new Date());
}

function monthKey() {
  return dayKey().slice(0, 7);
}

async function readBudgetState() {
  try {
    const result = await get(AI_BUDGET_PATH, { access: 'private', useCache: false });
    if (!result || result.statusCode !== 200) return {};
    return JSON.parse(await new Response(result.stream).text());
  } catch (_) {
    return {};
  }
}

async function writeBudgetState(state) {
  await put(AI_BUDGET_PATH, JSON.stringify(state), {
    access: 'private',
    allowOverwrite: true,
    addRandomSuffix: false,
    contentType: 'application/json; charset=utf-8',
    cacheControlMaxAge: 0
  });
}

async function reserveAiCall(provider) {
  const today = dayKey();
  const month = monthKey();
  const state = await readBudgetState();

  if (state.day !== today) {
    state.day = today;
    state.dailyCalls = 0;
  }
  if (state.month !== month) {
    state.month = month;
    state.monthlyCalls = 0;
  }

  const daily = Number(state.dailyCalls || 0);
  const monthly = Number(state.monthlyCalls || 0);

  if (daily >= DAILY_AI_CALL_LIMIT) {
    return { ok: false, reason: 'daily-call-limit', daily, monthly };
  }
  if (monthly >= MONTHLY_AI_CALL_LIMIT) {
    return { ok: false, reason: 'monthly-call-limit', daily, monthly };
  }

  state.dailyCalls = daily + 1;
  state.monthlyCalls = monthly + 1;
  state.lastProvider = provider;
  state.lastReservedAt = new Date().toISOString();
  await writeBudgetState(state);

  return {
    ok: true,
    daily: state.dailyCalls,
    monthly: state.monthlyCalls
  };
}

async function gatewayCreditStatus() {
  const token = process.env.AI_GATEWAY_API_KEY || process.env.VERCEL_OIDC_TOKEN;
  if (!token) return { ok: false, reason: 'no-gateway-auth', balance: null };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3500);
  try {
    const response = await fetch('https://ai-gateway.vercel.sh/v1/credits', {
      headers: { authorization: 'Bearer ' + token },
      signal: controller.signal
    });
    if (!response.ok) {
      return { ok: false, reason: 'credits-http-' + response.status, balance: null };
    }
    const data = await response.json();
    const balance = Number(data?.balance);
    const totalUsed = Number(data?.total_used);
    if (!Number.isFinite(balance)) {
      return { ok: false, reason: 'invalid-credit-balance', balance: null };
    }
    return {
      ok: true,
      balance,
      totalUsed: Number.isFinite(totalUsed) ? totalUsed : null
    };
  } catch (error) {
    return {
      ok: false,
      reason: 'credits-check-failed',
      balance: null,
      error: String(error?.message || error)
    };
  } finally {
    clearTimeout(timer);
  }
}

export async function getAIBudgetStatus() {
  const state = await readBudgetState();
  const credits = await gatewayCreditStatus();
  return {
    mode: 'free-credit-only',
    creditReserveUsd: FREE_CREDIT_RESERVE_USD,
    dailyCallLimit: DAILY_AI_CALL_LIMIT,
    monthlyCallLimit: MONTHLY_AI_CALL_LIMIT,
    dailyCalls: state.day === dayKey() ? Number(state.dailyCalls || 0) : 0,
    monthlyCalls: state.month === monthKey() ? Number(state.monthlyCalls || 0) : 0,
    gatewayBalanceUsd: credits.ok ? credits.balance : null,
    gatewayTotalUsedUsd: credits.ok ? credits.totalUsed : null,
    gatewayCreditCheckOk: Boolean(credits.ok),
    gatewayCreditCheckReason: credits.ok ? null : credits.reason
  };
}

async function openRouterConfig() {
  if (process.env.OPENROUTER_API_KEY) {
    return {
      key: process.env.OPENROUTER_API_KEY,
      model: process.env.OPENROUTER_MODEL || 'google/gemini-2.5-flash',
      visionModel: process.env.OPENROUTER_VISION_MODEL || process.env.OPENROUTER_MODEL || 'google/gemini-2.5-flash'
    };
  }

  if (openRouterCache && Date.now() - openRouterCacheAt < 10 * 60 * 1000) return openRouterCache;

  let cfg = await readOpenRouterConfig();
  if (!cfg) {
    await consumeProviderInbox();
    cfg = await readOpenRouterConfig();
  }
  if (!cfg?.key) return null;

  openRouterCache = cfg;
  openRouterCacheAt = Date.now();
  return cfg;
}

async function openRouterCall({ system, text, imageBytes, mimeType, maxTokens = 400 }) {
  if (process.env.ENABLE_EXTERNAL_AI_PROVIDERS !== '1') return null;
  const cfg = await openRouterConfig();
  if (!cfg?.key) return null;

  const content = [{ type: 'text', text }];
  if (imageBytes) {
    content.push({ type: 'image_url', image_url: { url: dataUrl(imageBytes, mimeType) } });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), imageBytes ? 15000 : 8000);
  try {
    const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        authorization: 'Bearer ' + cfg.key,
        'content-type': 'application/json',
        'HTTP-Referer': process.env.VERCEL_PROJECT_PRODUCTION_URL
          ? 'https://' + process.env.VERCEL_PROJECT_PRODUCTION_URL
          : 'https://telegram.org',
        'X-Title': 'Veshudei'
      },
      body: JSON.stringify({
        model: imageBytes
          ? (cfg.visionModel || cfg.model || 'google/gemini-2.5-flash')
          : (cfg.model || cfg.visionModel || 'google/gemini-2.5-flash'),
        temperature: 0.1,
        max_tokens: maxTokens,
        messages: [
          { role: 'system', content: system },
          { role: 'user', content }
        ]
      }),
      signal: controller.signal
    });

    if (!response.ok) {
      const body = await response.text().catch(() => '');
      throw new Error('OpenRouter HTTP ' + response.status + (body ? ': ' + body.slice(0, 180) : ''));
    }
    const data = await response.json();
    return String(data?.choices?.[0]?.message?.content || '').trim() || null;
  } finally {
    clearTimeout(timer);
  }
}

async function openAICall({ system, text, imageBytes, mimeType, maxTokens = 400 }) {
  if (process.env.ENABLE_EXTERNAL_AI_PROVIDERS !== '1') return null;
  const key = process.env.OPENAI_API_KEY;
  if (!key) return null;

  const userContent = [{ type: 'input_text', text }];
  if (imageBytes) userContent.push({ type: 'input_image', image_url: dataUrl(imageBytes, mimeType) });

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), imageBytes ? 15000 : 8000);
  try {
    const response = await fetch('https://api.openai.com/v1/responses', {
      method: 'POST',
      headers: { authorization: 'Bearer ' + key, 'content-type': 'application/json' },
      body: JSON.stringify({
        model: process.env.OPENAI_MODEL || 'gpt-4.1-mini',
        store: false,
        max_output_tokens: maxTokens,
        input: [
          { role: 'system', content: [{ type: 'input_text', text: system }] },
          { role: 'user', content: userContent }
        ]
      }),
      signal: controller.signal
    });
    if (!response.ok) throw new Error('OpenAI HTTP ' + response.status);
    return extractOpenAIResponseText(await response.json()) || null;
  } finally {
    clearTimeout(timer);
  }
}

async function gatewayCall({ system, text, imageBytes, mimeType, maxTokens = 400 }) {
  if (!process.env.AI_GATEWAY_API_KEY && !process.env.VERCEL_OIDC_TOKEN && process.env.ENABLE_VERCEL_AI_GATEWAY !== '1') return null;

  const credits = await gatewayCreditStatus();
  if (!credits.ok) {
    throw new Error('Gateway blocked: cannot verify free-credit balance (' + credits.reason + ')');
  }
  if (credits.balance <= FREE_CREDIT_RESERVE_USD) {
    throw new Error('Gateway blocked: free-credit reserve reached; balance=' + credits.balance.toFixed(4));
  }

  const reservation = await reserveAiCall('gateway');
  if (!reservation.ok) {
    throw new Error('Gateway blocked: ' + reservation.reason);
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), imageBytes ? 6000 : 4000);
  try {
    const { generateText } = await import('ai');
    const params = {
      model: process.env.AI_GATEWAY_MODEL || 'google/gemini-2.5-flash',
      system,
      maxOutputTokens: maxTokens,
      temperature: 0.1,
      abortSignal: controller.signal
    };
    if (imageBytes) {
      params.messages = [{
        role: 'user',
        content: [
          { type: 'text', text },
          { type: 'image', image: imageBytes, mediaType: mimeType || 'image/jpeg' }
        ]
      }];
    } else {
      params.prompt = text;
    }
    const result = await generateText(params);
    return String(result?.text || '').trim() || null;
  } finally {
    clearTimeout(timer);
  }
}

async function runProviders(args) {
  const errors = [];
  for (const [name, fn] of [
    ['gateway', gatewayCall],
    ['openrouter', openRouterCall],
    ['openai', openAICall]
  ]) {
    try {
      const answer = await fn(args);
      if (answer) return { text: answer, provider: name, errors };
    } catch (error) {
      errors.push(name + ': ' + String(error?.message || error));
    }
  }
  return { text: null, provider: null, errors };
}

export function modelText(args) {
  return runProviders({ ...args, imageBytes: null, mimeType: null });
}

export function modelVision(args) {
  return runProviders(args);
}
