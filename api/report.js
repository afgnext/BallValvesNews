// GET /api/report?date=YYYY-MM-DD&lang=es|en — devuelve el JSON de un día concreto desde Neon
const { Pool } = require('pg');

const pool = new Pool({
  connectionString: process.env.NEON_DATABASE_URL,
  ssl: { rejectUnauthorized: false },
});

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  const { date, lang = 'es' } = req.query;
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return res.status(400).json({ error: 'Parámetro date requerido (YYYY-MM-DD)' });
  }
  if (!['es', 'en'].includes(lang)) {
    return res.status(400).json({ error: 'lang debe ser "es" o "en"' });
  }

  try {
    const result = await pool.query(
      'SELECT raw_data FROM reports WHERE report_date = $1 AND lang = $2',
      [date, lang]
    );
    if (result.rows.length === 0) {
      return res.status(404).json({ error: `No hay informe [${lang}] para la fecha ${date}` });
    }
    return res.status(200).json(result.rows[0].raw_data);
  } catch (e) {
    console.error('report error:', e.message);
    return res.status(500).json({ error: e.message });
  }
};
