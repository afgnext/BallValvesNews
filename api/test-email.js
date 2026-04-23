const nodemailer = require('nodemailer');

module.exports = async function handler(req, res) {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, REPORT_URL } = process.env;

  if (!SMTP_HOST || !SMTP_USER || !SMTP_PASS) {
    return res.status(500).json({ error: 'SMTP no configurado en variables de entorno de Vercel' });
  }

  const to = req.body?.to || SMTP_USER;
  const reportUrl = REPORT_URL || 'https://tu-proyecto.vercel.app';

  const transporter = nodemailer.createTransport({
    host: SMTP_HOST,
    port: parseInt(SMTP_PORT || '587'),
    secure: false,
    auth: { user: SMTP_USER, pass: SMTP_PASS },
    tls: { ciphers: 'SSLv3' }
  });

  const html = `
  <html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px">
  <div style="max-width:580px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">
    <div style="background:#0d1117;padding:24px 28px">
      <span style="background:#e8a225;color:#000;font-weight:800;padding:5px 10px;border-radius:6px;font-size:13px">AFG</span>
      <span style="color:#e6edf3;font-size:16px;font-weight:600;margin-left:10px">Market Intelligence Radar</span>
      <p style="color:#7d8590;margin:6px 0 0;font-size:12px">Stainless Steel Balls · Oil &amp; Gas USA · Planta Michigan</p>
    </div>
    <div style="padding:24px 28px">
      <div style="background:#e8f5e9;border-left:4px solid #3fb950;padding:14px 18px;border-radius:0 8px 8px 0;margin-bottom:20px">
        <div style="font-size:13px;font-weight:700;color:#2e7d32">✅ Email de prueba — sistema funcionando correctamente</div>
        <div style="font-size:12px;color:#555;margin-top:4px">Las notificaciones diarias están configuradas y llegarán cada mañana a las 7:00h.</div>
      </div>
      <p style="color:#333;font-size:14px;margin-bottom:20px">Si recibes este mensaje, el sistema de alertas de AFG Market Intelligence está operativo.</p>
      <a href="${reportUrl}" style="display:block;background:#e8a225;color:#000;text-align:center;padding:13px;border-radius:8px;font-weight:700;font-size:14px;text-decoration:none">Ver informe completo</a>
    </div>
    <div style="background:#f8f9fa;padding:14px 28px;text-align:center;font-size:11px;color:#aaa">AFG Market Intelligence · Email de prueba</div>
  </div>
  </body></html>`;

  try {
    await transporter.sendMail({
      from: `AFG Intelligence <afgnext@alcortagroup.com>`,
      to,
      subject: '[TEST] AFG Market Radar — Prueba de notificación',
      html
    });
    return res.status(200).json({ ok: true, message: `Email enviado a ${to}` });
  } catch (e) {
    console.error('SMTP error:', e);
    return res.status(500).json({ error: e.message });
  }
}
