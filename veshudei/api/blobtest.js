export default async function handler(req, res) {
  return res.status(410).json({ ok: false, disabled: true, message: 'Blob test endpoint disabled after successful read/write verification.' });
}
