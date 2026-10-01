export default async function handler(req, res) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const { generateText } = await import('ai');
    const result = await generateText({
      model: 'openai/gpt-5.6-sol',
      prompt: 'Ответь ровно одним словом: OK',
      maxOutputTokens: 16,
      temperature: 0,
      abortSignal: controller.signal
    });
    return res.status(200).json({ ok: true, text: String(result.text || '').trim() });
  } catch (error) {
    return res.status(200).json({ ok: false, error: String(error?.message || error) });
  } finally {
    clearTimeout(timer);
  }
}
