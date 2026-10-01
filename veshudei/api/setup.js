export default async function handler(req, res) {
  return res.status(410).json({ ok: false, disabled: true, message: 'Setup endpoint disabled after successful webhook configuration.' });
}
