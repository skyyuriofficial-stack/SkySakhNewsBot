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

async function openRouterConfig() {
  if (process.env.OPENROUTER_API_KEY) {
    return {
      key: process.env.OPENROUTER_API_KEY,
      model: process.env.OPENROUTER_MODEL || null,
      visionModel: process.env.OPENROUTER_VISION_MODEL || null
    };
  }

  if (openRouterCache && Date.now() - openRouterCacheAt < 5 * 60 * 1000) return openRouterCache;

  try {
    const { get } = await import('@vercel/blob');
    const result = await get('veshudei/secrets/openrouter.json', { access: 'private', useCache: false });
    if (!result || result.statusCode !== 200) return null;
    const raw = await new Response(result.stream).text();
    const cfg = JSON.parse(raw);
    if (!cfg?.key) return null;
    openRouterCache = {
      key: String(cfg.key),
      model: cfg.model ? String(cfg.model) : null,
      visionModel: cfg.visionModel ? String(cfg.visionModel) : null
    };
    openRouterCacheAt = Date.now();
    return openRouterCache;
  } catch (_) {
    return null;
  }
}

async function openRouterCall({ system, text, imageBytes, mimeType, maxTokens = 400 }) {
  const cfg = await openRouterConfig();
  const key = cfg?.key;
  if (!key) return null;

  const content = [{ type: 'text', text }];
  if (imageBytes) content.push({ type: 'image_url', image_url: { url: dataUrl(imageBytes, mimeType) } });

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        authorization: 'Bearer ' + key,
        'content-type': 'application/json',
        'HTTP-Referer': process.env.VERCEL_PROJECT_PRODUCTION_URL ? 'https://' + process.env.VERCEL_PROJECT_PRODUCTION_URL : 'https://telegram.org',
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
    if (!response.ok) throw new Error('OpenRouter HTTP ' + response.status);
    const data = await response.json();
    return String(data?.choices?.[0]?.message?.content || '').trim() || null;
  } finally {
    clearTimeout(timer);
  }
}

async function openAICall({ system, text, imageBytes, mimeType, maxTokens = 400 }) {
  const key = process.env.OPENAI_API_KEY;
  if (!key) return null;

  const userContent = [{ type: 'input_text', text }];
  if (imageBytes) userContent.push({ type: 'input_image', image_url: dataUrl(imageBytes, mimeType) });

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
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
  if (!process.env.AI_GATEWAY_API_KEY && !process.env.VERCEL_OIDC_TOKEN && process.env.ENABLE_VERCEL_AI_GATEWAY !== '1') {
    return null;
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const { generateText } = await import('ai');
    const params = {
      model: process.env.AI_GATEWAY_MODEL || 'openai/gpt-5.6-sol',
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
  for (const provider of [
    ['openrouter', openRouterCall],
    ['openai', openAICall],
    ['gateway', gatewayCall]
  ]) {
    try {
      const answer = await provider[1](args);
      if (answer) return { text: answer, provider: provider[0], errors };
    } catch (error) {
      errors.push(provider[0] + ': ' + String(error?.message || error));
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
