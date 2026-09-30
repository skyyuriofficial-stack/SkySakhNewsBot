import { telegram } from '../lib/telegram.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).json({ ok: false });
  if (!process.env.SETUP_KEY || req.query.key !== process.env.SETUP_KEY) return res.status(401).json({ ok: false, error: 'unauthorized' });
  try {
    const proto = req.headers['x-forwarded-proto'] || 'https';
    const host = req.headers.host;
    const webhook = proto + '://' + host + '/api/telegram';
    const me = await telegram('getMe');
    const hook = await telegram('setWebhook', { url: webhook, allowed_updates: ['message', 'callback_query'], drop_pending_updates: true });
    await telegram('setMyCommands', { commands: [
      { command: 'start', description: 'Подключить дневник' },
      { command: 'menu', description: 'Открыть меню' },
      { command: 'today', description: 'Показать записи за сегодня' }
    ]});
    return res.status(200).json({ ok: true, bot: '@' + me.username, webhook, telegram: hook });
  } catch (error) {
    return res.status(500).json({ ok: false, error: String(error?.message || error) });
  }
}
