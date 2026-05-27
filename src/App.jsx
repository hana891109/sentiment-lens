import { useState, useEffect, useCallback } from "react";

// ─── Helpers ─────────────────────────────────────────────────────────────────
function fmt(n) {
  if (n === undefined || n === null) return "—";
  if (n < 0.00001) return n.toFixed(8);
  if (n < 0.001) return n.toFixed(6);
  if (n < 1) return n.toFixed(4);
  if (n < 100) return n.toFixed(2);
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function timeAgo(ts) {
  const diff = Math.floor((Date.now() / 1000 - ts) / 60);
  if (diff < 1) return "剛剛";
  if (diff < 60) return `${diff} 分鐘前`;
  return `${Math.floor(diff / 60)} 小時前`;
}

const ROLE_COLORS = {
  "獵頭者": "#00c882", "先鋒者": "#00b4d8", "衝鋒者": "#48cae4",
  "沉思者": "#ff4659", "獵空者": "#e63946", "伏擊者": "#ff6b6b",
};

// ─── UI Components ────────────────────────────────────────────────────────────

function LiveDot() {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{
        width: 7, height: 7, borderRadius: "50%", background: "#00c882",
        boxShadow: "0 0 8px #00c882", display: "inline-block",
        animation: "pulse 2s infinite",
      }} />
      <span style={{ fontSize: 11, color: "#555" }}>即時更新</span>
    </span>
  );
}

function DirectionBadge({ dir }) {
  const isLong = dir === "LONG";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "5px 12px", borderRadius: 7, fontSize: 12, fontWeight: 700, letterSpacing: 0.8,
      background: isLong ? "rgba(0,200,130,0.12)" : "rgba(255,70,89,0.12)",
      color: isLong ? "#00c882" : "#ff4659",
      border: `1px solid ${isLong ? "rgba(0,200,130,0.3)" : "rgba(255,70,89,0.3)"}`,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: isLong ? "#00c882" : "#ff4659",
        boxShadow: `0 0 5px ${isLong ? "#00c882" : "#ff4659"}`,
      }} />
      看{isLong ? "漲" : "跌"} {dir}
    </span>
  );
}

function FTPBadge() {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "5px 12px", borderRadius: 7, fontSize: 12, fontWeight: 700,
      background: "rgba(255,200,0,0.1)", color: "#ffc800",
      border: "1px solid rgba(255,200,0,0.3)",
    }}>👑 達到 FTP</span>
  );
}

function TP_Badge({ n }) {
  const colors = { 1: "#6ee7b7", 2: "#34d399", 3: "#10b981", 4: "#ffc800" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "3px 8px", borderRadius: 5, fontSize: 10, fontWeight: 700,
      background: `${colors[n]}20`, color: colors[n],
      border: `1px solid ${colors[n]}40`,
    }}>
      {n === 4 ? "👑 FTP" : `TP${n}`}
    </span>
  );
}

function PnlDisplay({ pnl, big }) {
  const pos = pnl >= 0;
  return (
    <span style={{
      fontFamily: "'DM Mono', monospace",
      fontSize: big ? 38 : 20,
      fontWeight: 900,
      color: pos ? "#00c882" : "#ff4659",
      lineHeight: 1,
    }}>
      {pos ? "+" : ""}{pnl}%
    </span>
  );
}

// ─── Signal Card ─────────────────────────────────────────────────────────────
function SignalCard({ s, onClick }) {
  const isLong = s.direction === "LONG";
  const accent = isLong ? "#00c882" : "#ff4659";
  const reachedFTP = s.reached_tp === 4;

  return (
    <div
      onClick={() => onClick(s)}
      style={{
        background: "linear-gradient(145deg,#131820,#0e1318)",
        border: `1px solid ${reachedFTP ? "rgba(255,200,0,0.2)" : `${accent}22`}`,
        borderRadius: 16, padding: 20, cursor: "pointer",
        transition: "transform 0.18s, box-shadow 0.18s",
        boxShadow: `0 4px 24px ${accent}0d, inset 0 1px 0 rgba(255,255,255,0.04)`,
        position: "relative", overflow: "hidden",
        animation: "fadeIn 0.3s ease both",
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = "translateY(-3px)";
        e.currentTarget.style.boxShadow = `0 10px 36px ${accent}22, inset 0 1px 0 rgba(255,255,255,0.06)`;
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.boxShadow = `0 4px 24px ${accent}0d, inset 0 1px 0 rgba(255,255,255,0.04)`;
      }}
    >
      {/* Glow corner */}
      <div style={{
        position: "absolute", top: 0, right: 0, width: 80, height: 80,
        background: `radial-gradient(circle at top right,${accent}18,transparent)`,
        pointerEvents: "none",
      }} />

      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
            <span style={{ fontSize: 18, fontWeight: 900, color: "#fff", letterSpacing: 1 }}>{s.symbol}</span>
            <span style={{ fontSize: 10, color: "#555", background: "rgba(255,255,255,0.05)", padding: "2px 6px", borderRadius: 4, fontFamily: "'DM Mono',monospace" }}>
              {s.timeframe}
            </span>
          </div>
          <div style={{ fontSize: 11, color: ROLE_COLORS[s.role] || "#666" }}>{s.role}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <PnlDisplay pnl={s.pnl} />
          <div style={{ fontSize: 9, color: "#444", marginTop: 3 }}>累計盈虧</div>
        </div>
      </div>

      {/* Badges */}
      <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
        <DirectionBadge dir={s.direction} />
        {s.reached_tp > 0 && <TP_Badge n={s.reached_tp} />}
        {reachedFTP && <FTPBadge />}
      </div>

      {/* Price grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 10 }}>
        {[
          { label: "觸發價", value: `$${fmt(s.trigger)}`, color: "#ccc" },
          { label: "當前價", value: s.current ? `$${fmt(s.current)}` : "—", color: "#aaa" },
          { label: "止損 SL", value: `$${fmt(s.sl)}`, color: "#ff4659" },
          { label: "風險 R", value: `${s.risk_pct}%`, color: "#ff6b6b" },
        ].map((d, i) => (
          <div key={i} style={{ background: "rgba(255,255,255,0.03)", borderRadius: 8, padding: "8px 10px", border: "1px solid rgba(255,255,255,0.05)" }}>
            <div style={{ fontSize: 9, color: "#555", marginBottom: 3 }}>{d.label}</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: d.color, fontFamily: "'DM Mono',monospace" }}>{d.value}</div>
          </div>
        ))}
      </div>

      {/* TP Row */}
      <div style={{ display: "flex", gap: 4 }}>
        {[s.tp1, s.tp2, s.tp3].map((tp, i) => {
          const hit = s.reached_tp > i;
          return (
            <div key={i} style={{
              flex: 1, borderRadius: 6, padding: "5px 0", textAlign: "center",
              background: hit ? "rgba(0,200,130,0.08)" : "rgba(255,255,255,0.03)",
              border: `1px solid ${hit ? "rgba(0,200,130,0.25)" : "rgba(255,255,255,0.06)"}`,
            }}>
              <div style={{ fontSize: 9, color: hit ? "#00c882" : "#555", marginBottom: 2 }}>TP{i + 1}</div>
              <div style={{ fontSize: 11, color: hit ? "#00c882" : "#888", fontFamily: "'DM Mono',monospace" }}>${fmt(tp)}</div>
            </div>
          );
        })}
        <div style={{
          flex: 1, borderRadius: 6, padding: "5px 0", textAlign: "center",
          background: reachedFTP ? "rgba(255,200,0,0.1)" : "rgba(255,255,255,0.03)",
          border: `1px solid ${reachedFTP ? "rgba(255,200,0,0.35)" : "rgba(255,255,255,0.06)"}`,
        }}>
          <div style={{ fontSize: 9, color: "#ffc800", marginBottom: 2 }}>FTP</div>
          <div style={{ fontSize: 11, color: "#ffc800", fontFamily: "'DM Mono',monospace" }}>${fmt(s.ftp)}</div>
        </div>
      </div>

      {/* Time */}
      <div style={{ marginTop: 10, fontSize: 10, color: "#3a3a3a", textAlign: "center" }}>
        觸發於 {s.triggered_at}（{timeAgo(s.timestamp)}）
      </div>
    </div>
  );
}

// ─── Detail Modal ─────────────────────────────────────────────────────────────
function Modal({ s, onClose }) {
  if (!s) return null;
  const isLong = s.direction === "LONG";
  const accent = isLong ? "#00c882" : "#ff4659";

  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 999, background: "rgba(0,0,0,0.88)", backdropFilter: "blur(14px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
      onClick={onClose}
    >
      <div
        style={{
          background: "linear-gradient(160deg,#131820,#0d1117)",
          border: `1px solid ${accent}33`,
          borderRadius: 22, padding: 28, width: "100%", maxWidth: 400,
          boxShadow: `0 32px 96px ${accent}18`, animation: "fadeIn 0.2s ease both",
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Logo */}
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ width: 7, height: 7, borderRadius: "50%", background: "#00c882", boxShadow: "0 0 8px #00c882", animation: "pulse 2s infinite" }} />
              <span style={{ fontSize: 11, color: "#555", letterSpacing: 1 }}>CRYPTO TRADERS CLUB</span>
            </div>
            <div style={{ fontSize: 10, color: "#3a3a3a", marginTop: 2 }}>Sentiment Lens · 數據交易訊號</div>
          </div>
          <button onClick={onClose} style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.08)", color: "#666", borderRadius: 8, width: 30, height: 30, cursor: "pointer", fontSize: 14 }}>✕</button>
        </div>

        {/* Symbol */}
        <div style={{ marginBottom: 4 }}>
          <span style={{ fontSize: 34, fontWeight: 900, color: "#fff", letterSpacing: 2 }}>{s.symbol}</span>
          <span style={{ fontSize: 15, color: "#555", marginLeft: 10 }}>{s.timeframe}</span>
        </div>
        <div style={{ fontSize: 12, color: ROLE_COLORS[s.role] || "#666", marginBottom: 16 }}>{s.role}</div>

        <div style={{ display: "flex", gap: 8, marginBottom: 18, flexWrap: "wrap" }}>
          <DirectionBadge dir={s.direction} />
          {s.reached_tp === 4 && <FTPBadge />}
        </div>

        {/* PnL big */}
        <div style={{
          background: `${accent}0d`, border: `1px solid ${accent}22`,
          borderRadius: 12, padding: "16px 20px", marginBottom: 14,
        }}>
          <div style={{ fontSize: 11, color: "#555", marginBottom: 6 }}>累計盈虧</div>
          <PnlDisplay pnl={s.pnl} big />
        </div>

        {/* Grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7, marginBottom: 7 }}>
          {[
            { l: "觸發價", v: `$${fmt(s.trigger)}`, c: "#ccc" },
            { l: "當前價", v: s.current ? `$${fmt(s.current)}` : "—", c: "#aaa" },
            { l: "止損 SL", v: `$${fmt(s.sl)}`, c: "#ff4659" },
            { l: "風險 R", v: `${s.risk_pct}%`, c: "#ff6b6b" },
            { l: "TP1", v: `$${fmt(s.tp1)}`, c: "#00c882" },
            { l: "TP2", v: `$${fmt(s.tp2)}`, c: "#00c882" },
            { l: "TP3", v: `$${fmt(s.tp3)}`, c: "#00c882" },
            { l: "FTP 👑", v: `$${fmt(s.ftp)}`, c: "#ffc800", hi: true },
          ].map((d, i) => (
            <div key={i} style={{
              background: d.hi ? "rgba(255,200,0,0.05)" : "rgba(255,255,255,0.03)",
              border: `1px solid ${d.hi ? "rgba(255,200,0,0.3)" : "rgba(255,255,255,0.06)"}`,
              borderRadius: 9, padding: "10px 12px",
            }}>
              <div style={{ fontSize: 10, color: "#555", marginBottom: 4 }}>{d.l}</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: d.c, fontFamily: "'DM Mono',monospace" }}>{d.v}</div>
            </div>
          ))}
        </div>

        {/* Futures data */}
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.05)", paddingTop: 14, marginTop: 8, marginBottom: 14 }}>
          <div style={{ fontSize: 10, color: "#444", letterSpacing: 1, marginBottom: 10 }}>期貨數據</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 7 }}>
            {[
              { l: "多空比 LSR", v: s.lsr, c: s.lsr > 1 ? "#00c882" : "#ff4659" },
              { l: "資金費率", v: `${s.funding >= 0 ? "+" : ""}${s.funding}%`, c: s.funding >= 0 ? "#ff6b6b" : "#00c882" },
              { l: "未平倉量", v: `${s.oi}M`, c: "#aaa" },
            ].map((d, i) => (
              <div key={i} style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)", borderRadius: 8, padding: "8px", textAlign: "center" }}>
                <div style={{ fontSize: 9, color: "#444", marginBottom: 4 }}>{d.l}</div>
                <div style={{ fontSize: 13, fontWeight: 700, color: d.c, fontFamily: "'DM Mono',monospace" }}>{d.v}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ fontSize: 10, color: "#3a3a3a", textAlign: "center" }}>
          觸發於 {s.triggered_at}（{timeAgo(s.timestamp)}）
        </div>
        <div style={{ fontSize: 10, color: "#252525", textAlign: "center", marginTop: 6 }}>
          cryptotradersclub.org/sentiment
        </div>
      </div>
    </div>
  );
}

// ─── Filter Bar ───────────────────────────────────────────────────────────────
function FilterBar({ dir, setDir, tf, setTf, reachedOnly, setReachedOnly, search, setSearch }) {
  const btn = (active, label, onClick, color) => (
    <button key={label} onClick={onClick} style={{
      padding: "6px 13px", borderRadius: 7, fontSize: 11, fontWeight: active ? 700 : 400, cursor: "pointer",
      border: `1px solid ${active ? "rgba(255,255,255,0.18)" : "rgba(255,255,255,0.07)"}`,
      background: active ? "rgba(255,255,255,0.09)" : "transparent",
      color: active ? (color || "#ddd") : "#555", transition: "all 0.15s",
    }}>{label}</button>
  );

  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20, alignItems: "center" }}>
      <input
        value={search}
        onChange={e => setSearch(e.target.value.toUpperCase())}
        placeholder="搜尋幣種..."
        style={{
          background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: 7, padding: "6px 12px", color: "#ccc", fontSize: 12,
          outline: "none", width: 120, fontFamily: "'DM Mono',monospace",
        }}
      />
      <div style={{ width: 1, height: 20, background: "rgba(255,255,255,0.07)" }} />
      {[["ALL","全部"], ["LONG","做多","#00c882"], ["SHORT","做空","#ff4659"]].map(([d, l, c]) =>
        btn(dir === d, l, () => setDir(d), c)
      )}
      <div style={{ width: 1, height: 20, background: "rgba(255,255,255,0.07)" }} />
      {["ALL","5M","15M","1H","4H"].map(t =>
        btn(tf === t, t === "ALL" ? "所有週期" : t, () => setTf(t))
      )}
      <div style={{ width: 1, height: 20, background: "rgba(255,255,255,0.07)" }} />
      {btn(reachedOnly, "👑 FTP 達成", () => setReachedOnly(!reachedOnly), "#ffc800")}
    </div>
  );
}

// ─── Stats Row ────────────────────────────────────────────────────────────────
function Stats({ signals }) {
  const longs  = signals.filter(s => s.direction === "LONG").length;
  const shorts = signals.filter(s => s.direction === "SHORT").length;
  const ftp    = signals.filter(s => s.reached_tp === 4).length;
  const active = signals.filter(s => s.active !== false).length;
  const avgPnl = signals.length ? (signals.reduce((a, s) => a + (s.pnl || 0), 0) / signals.length).toFixed(1) : "0.0";

  return (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 24 }}>
      {[
        { l: "總訊號", v: signals.length, c: "#aaa" },
        { l: "活躍中", v: active, c: "#00c882" },
        { l: "做多", v: longs, c: "#00c882" },
        { l: "做空", v: shorts, c: "#ff4659" },
        { l: "👑 達到 FTP", v: ftp, c: "#ffc800" },
        { l: "平均盈虧", v: `+${avgPnl}%`, c: "#00c882" },
      ].map((s, i) => (
        <div key={i} style={{
          background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)",
          borderRadius: 10, padding: "10px 16px", textAlign: "center",
        }}>
          <div style={{ fontSize: 20, fontWeight: 900, color: s.c, fontFamily: "'DM Mono',monospace" }}>{s.v}</div>
          <div style={{ fontSize: 10, color: "#555", marginTop: 2 }}>{s.l}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Empty State ──────────────────────────────────────────────────────────────
function Empty({ loading }) {
  return (
    <div style={{ textAlign: "center", padding: "80px 0", color: "#444" }}>
      <div style={{ fontSize: 48, marginBottom: 16 }}>{loading ? "⏳" : "📭"}</div>
      <div style={{ fontSize: 16, marginBottom: 8 }}>{loading ? "載入中..." : "尚無訊號"}</div>
      <div style={{ fontSize: 12, color: "#333" }}>
        {loading ? "正在連接數據源" : "執行 python fetcher.py 開始掃描訊號"}
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [signals,      setSignals]      = useState([]);
  const [loading,      setLoading]      = useState(true);
  const [lastUpdate,   setLastUpdate]   = useState("");
  const [selected,     setSelected]     = useState(null);
  const [dirFilter,    setDirFilter]    = useState("ALL");
  const [tfFilter,     setTfFilter]     = useState("ALL");
  const [reachedOnly,  setReachedOnly]  = useState(false);
  const [search,       setSearch]       = useState("");
  const [error,        setError]        = useState(null);

  const loadSignals = useCallback(async () => {
    try {
      // signals.json は同じフォルダに置く
      const res = await fetch("https://sentiment-lens-api.onrender.com/signals?" + Date.now());
      if (!res.ok) throw new Error("signals.json が見つかりません");
      const data = await res.json();
      setSignals(data.signals || []);
      setLastUpdate(data.updated_at || "");
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSignals();
    const id = setInterval(loadSignals, 60_000); // 每 60 秒自動重新載入
    return () => clearInterval(id);
  }, [loadSignals]);

  const filtered = signals.filter(s => {
    if (search && !s.symbol.includes(search)) return false;
    if (dirFilter !== "ALL" && s.direction !== dirFilter) return false;
    if (tfFilter !== "ALL" && s.timeframe !== tfFilter) return false;
    if (reachedOnly && s.reached_tp !== 4) return false;
    return true;
  });

  return (
    <div style={{ minHeight: "100vh", background: "#080c10", color: "#e8e8e8", fontFamily: "'Noto Sans TC',-apple-system,sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Noto+Sans+TC:wght@400;700;900&display=swap');
        *{box-sizing:border-box;margin:0;padding:0;}
        ::-webkit-scrollbar{width:5px}
        ::-webkit-scrollbar-track{background:#080c10}
        ::-webkit-scrollbar-thumb{background:#1e2530;border-radius:3px}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
        @keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
      `}</style>

      {/* ── Navbar ── */}
      <div style={{
        borderBottom: "1px solid rgba(255,255,255,0.05)",
        background: "rgba(8,12,16,0.97)", backdropFilter: "blur(20px)",
        position: "sticky", top: 0, zIndex: 100, padding: "0 24px",
      }}>
        <div style={{ maxWidth: 1200, margin: "0 auto", height: 58, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 34, height: 34, borderRadius: 9,
              background: "linear-gradient(135deg,#00c882,#005540)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 17, boxShadow: "0 0 14px rgba(0,200,130,0.3)",
            }}>⚡</div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 900, color: "#fff", letterSpacing: 1 }}>CRYPTO TRADERS CLUB</div>
              <div style={{ fontSize: 10, color: "#444" }}>Sentiment Lens · 數據交易訊號</div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {lastUpdate && <span style={{ fontSize: 10, color: "#444" }}>更新：{lastUpdate}</span>}
            <LiveDot />
            <button onClick={loadSignals} style={{
              background: "rgba(0,200,130,0.1)", border: "1px solid rgba(0,200,130,0.2)",
              color: "#00c882", borderRadius: 7, padding: "5px 12px", fontSize: 11,
              cursor: "pointer", fontWeight: 700,
            }}>↻ 刷新</button>
          </div>
        </div>
      </div>

      {/* ── Body ── */}
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 24px" }}>

        <div style={{ marginBottom: 26 }}>
          <h1 style={{ fontSize: 26, fontWeight: 900, color: "#fff", marginBottom: 6 }}>數據交易訊號</h1>
          <p style={{ fontSize: 12, color: "#555" }}>
            基於資金費率 · 多空比 · 未平倉量的自動化訊號 · Binance 期貨數據
          </p>
        </div>

        {error && (
          <div style={{ background: "rgba(255,70,89,0.08)", border: "1px solid rgba(255,70,89,0.2)", borderRadius: 10, padding: "14px 18px", marginBottom: 20, fontSize: 13, color: "#ff6b6b" }}>
            ⚠️ 無法載入訊號：{error}
            <br />
            <span style={{ fontSize: 11, color: "#ff4659", marginTop: 4, display: "block" }}>
              請先執行 <code style={{ background: "rgba(255,255,255,0.06)", padding: "1px 6px", borderRadius: 4 }}>python fetcher.py</code>，再把 signals.json 放到同目錄下
            </span>
          </div>
        )}

        {signals.length > 0 && <Stats signals={signals} />}

        <FilterBar
          dir={dirFilter} setDir={setDirFilter}
          tf={tfFilter} setTf={setTfFilter}
          reachedOnly={reachedOnly} setReachedOnly={setReachedOnly}
          search={search} setSearch={setSearch}
        />

        {loading || filtered.length === 0 ? (
          <Empty loading={loading} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(295px,1fr))", gap: 14 }}>
            {filtered.map((s, i) => (
              <div key={s.id} style={{ animationDelay: `${i * 0.025}s`, animation: "fadeIn 0.3s ease both" }}>
                <SignalCard s={s} onClick={setSelected} />
              </div>
            ))}
          </div>
        )}

        <div style={{ textAlign: "center", marginTop: 60, paddingTop: 20, borderTop: "1px solid rgba(255,255,255,0.04)" }}>
          <div style={{ fontSize: 10, color: "#2a2a2a" }}>cryptotradersclub.org/sentiment</div>
          <div style={{ fontSize: 10, color: "#222", marginTop: 4 }}>本平台訊號僅供參考，不構成投資建議。交易有風險，入市需謹慎。</div>
        </div>
      </div>

      {selected && <Modal s={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
