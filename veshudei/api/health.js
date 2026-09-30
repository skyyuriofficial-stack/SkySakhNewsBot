export default async function handler(req, res) {
  return res.status(200).json({ ok: true, service: '@veshudei_bot', time: new Date().toISOString() });
}
