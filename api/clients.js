// GET  /api/clients        — lista todos los clientes manuales
// POST /api/clients        — añade un cliente nuevo
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

  // ── GET: listar clientes ────────────────────────────────────────────────
  if (req.method === 'GET') {
    try {
      const result = await pool.query(
        'SELECT * FROM clients ORDER BY priority_order, created_at DESC'
      );
      return res.status(200).json({ clients: result.rows });
    } catch (e) {
      console.error('clients GET error:', e.message);
      return res.status(500).json({ error: e.message });
    }
  }

  // ── POST: añadir cliente ────────────────────────────────────────────────
  if (req.method === 'POST') {
    const { name, type, url, city, lat, lng, notes, priority } = req.body || {};
    if (!name || !type) {
      return res.status(400).json({ error: 'name y type son obligatorios' });
    }
    const priorityOrder = { Alta: 1, Media: 2, Baja: 3 }[priority] || 2;
    try {
      const result = await pool.query(
        `INSERT INTO clients (name, type, url, city, lat, lng, notes, priority, priority_order)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *`,
        [name, type, url || null, city || null,
         lat ? parseFloat(lat) : null, lng ? parseFloat(lng) : null,
         notes || null, priority || 'Media', priorityOrder]
      );
      return res.status(201).json({ client: result.rows[0] });
    } catch (e) {
      console.error('clients POST error:', e.message);
      return res.status(500).json({ error: e.message });
    }
  }

  return res.status(405).json({ error: 'Method not allowed' });
};
