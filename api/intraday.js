export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  if (req.method === "OPTIONS") { res.status(200).end(); return; }
  try {
    const r = await fetch(
      process.env.INTRADAY_API_URL || "https://sentiment-lens-intraday.onrender.com/signals"
    );
    const data = await r.json();
    res.status(200).json(data);
  } catch(e) {
    res.status(200).json({ error: e.message, signals: [], total: 0, updated_at: "", win_rate: 0 });
  }
}
