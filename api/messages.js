// GET  /api/messages          — últimos 200 mensajes
// POST /api/messages          — envía un mensaje nuevo
const { Pool } = require('pg');

const pool = new Pool({
  connectionString: process.env.NEON_DATABASE_URL,
  ssl: { rejectUnauthorized: false },
});

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();

  // ── GET ────────────────────────────────────────────────────────────────
  if (req.method === 'GET') {
    try {
      const result = await pool.query(`
        SELECT id, user_name, avatar, message, created_at
        FROM messages
        ORDER BY created_at ASC
        LIMIT 200
      `);
      return res.status(200).json({ messages: result.rows });
    } catch (e) {
      console.error('messages GET:', e.message);
      return res.status(500).json({ error: e.message });
    }
  }

  // ── POST ───────────────────────────────────────────────────────────────
  if (req.method === 'POST') {
    const { user_name, avatar, message } = req.body || {};
    if (!user_name || !message?.trim()) {
      return res.status(400).json({ error: 'user_name y message son obligatorios' });
    }
    try {
      const result = await pool.query(
        `INSERT INTO messages (user_name, avatar, message)
         VALUES ($1, $2, $3) RETURNING *`,
        [user_name, avatar || '👤', message.trim()]
      );
      return res.status(201).json({ message: result.rows[0] });
    } catch (e) {
      console.error('messages POST:', e.message);
      return res.status(500).json({ error: e.message });
    }
  }

  return res.status(405).json({ error: 'Method not allowed' });
};
