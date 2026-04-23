// GET /api/reports — devuelve la lista de fechas disponibles en Neon
const { Pool } = require('pg');

const pool = new Pool({
  connectionString: process.env.NEON_DATABASE_URL,
  ssl: { rejectUnauthorized: false },
});

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  try {
    const result = await pool.query(
      'SELECT report_date FROM reports ORDER BY report_date DESC LIMIT 90'
    );
    const dates = result.rows.map(r => {
      const d = new Date(r.report_date);
      return d.toISOString().split('T')[0];
    });
    return res.status(200).json({ dates });
  } catch (e) {
    console.error('reports error:', e.message);
    return res.status(500).json({ error: e.message });
  }
};
