// Envío de email vía Gmail SMTP con App Password
// Variables de entorno requeridas en Vercel:
//   SMTP_USER (afgnext100@gmail.com), SMTP_PASS (App Password de 16 chars), REPORT_URL

const nodemailer = require('nodemailer');

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { SMTP_USER, SMTP_PASS, REPORT_URL } = process.env;

  if (!SMTP_USER || !SMTP_PASS) {
    return res.status(500).json({ error: 'Faltan SMTP_USER o SMTP_PASS en las variables de entorno de Vercel' });
  }

  const to        = req.body?.to || SMTP_USER;
  const reportUrl = REPORT_URL || '#';

  const transporter = nodemailer.createTransport({
    host: 'smtp.gmail.com',
    port: 587,
    secure: false,
    auth: { user: SMTP_USER, pass: SMTP_PASS },
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
        <div style="font-size:12px;color:#555;margin-top:4px">Las notificaciones diarias llegarán cada mañana a las 7:00h (lunes a viernes).</div>
      </div>
      <p style="color:#333;font-size:14px;margin-bottom:20px">Si recibes este mensaje, el sistema de alertas de AFG Market Intelligence está operativo.</p>
      <a href="${reportUrl}" style="display:block;background:#e8a225;color:#000;text-align:center;padding:13px;border-radius:8px;font-weight:700;font-size:14px;text-decoration:none">Ver informe completo</a>
    </div>
    <div style="background:#f8f9fa;padding:14px 28px;text-align:center;font-size:11px;color:#aaa">AFG Market Intelligence · Email de prueba</div>
  </div>
  </body></html>`;

  try {
    await transporter.sendMail({
      from: `AFG Intelligence <${SMTP_USER}>`,
      to,
      subject: '[TEST] AFG Market Radar — Prueba de notificación',
      html,
    });
    return res.status(200).json({ ok: true, message: `Email enviado a ${to}` });
  } catch (e) {
    console.error('Gmail SMTP error:', e.message);
    return res.status(500).json({ error: e.message });
  }
};
