import { useState, useEffect, useCallback } from "react";

// ─── Helpers ──────────────────────────────────────────────
function fmt(n) {
  if (n === undefined || n === null) return "—";
  if (n < 0.00001) return n.toFixed(8);
  if (n < 0.001)   return n.toFixed(6);
  if (n < 1)       return n.toFixed(4);
  if (n < 100)     return n.toFixed(2);
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function timeAgo(ts) {
  const diff = Math.floor((Date.now()/1000 - ts) / 60);
  if (diff < 1)  return "剛剛";
  if (diff < 60) return diff + " 分鐘前";
  return Math.floor(diff/60) + " 小時前";
}

// ─── Badge Components ──────────────────────────────────────
function DirectionBadge({ dir }) {
  const isLong = dir === "LONG";
  return (
    <span style={{
      display:"inline-flex", alignItems:"center", gap:6,
      padding:"5px 12px", borderRadius:7, fontSize:12, fontWeight:700,
      background: isLong ? "rgba(0,200,130,0.12)" : "rgba(255,70,89,0.12)",
      color: isLong ? "#00c882" : "#ff4659",
      border:`1px solid ${isLong ? "rgba(0,200,130,0.3)" : "rgba(255,70,89,0.3)"}`,
    }}>
      <span style={{width:6,height:6,borderRadius:"50%",background:isLong?"#00c882":"#ff4659",boxShadow:`0 0 5px ${isLong?"#00c882":"#ff4659"}`}}/>
      看{isLong?"漲":"跌"} {dir}
    </span>
  );
}

function FTPBadge() {
  return (
    <span style={{
      display:"inline-flex",alignItems:"center",gap:4,
      padding:"5px 10px",borderRadius:7,fontSize:11,fontWeight:700,
      background:"rgba(255,200,0,0.1)",color:"#ffc800",
      border:"1px solid rgba(255,200,0,0.3)",
    }}>👑 FTP</span>
  );
}

function TypeBadge({ type, mode }) {
  const isCounter = type === "反轉";
  const isIntraday = type === "日內";
  let bg, color, border, label;
  if (isIntraday) {
    bg = "rgba(100,150,255,0.12)"; color = "#6496ff";
    border = "1px solid rgba(100,150,255,0.3)"; label = "⚡ " + (mode||"日內");
  } else if (isCounter) {
    bg = "rgba(255,165,0,0.12)"; color = "#ffa500";
    border = "1px solid rgba(255,165,0,0.3)"; label = "↺ 反轉";
  } else {
    bg = "rgba(100,255,180,0.08)"; color = "#64ffb4";
    border = "1px solid rgba(100,255,180,0.2)"; label = "→ 順勢";
  }
  return (
    <span style={{display:"inline-flex",alignItems:"center",padding:"3px 8px",
      borderRadius:5,fontSize:10,fontWeight:700,background:bg,color,border}}>
      {label}
    </span>
  );
}

// ─── Signal Card ───────────────────────────────────────────
function SignalCard({ s, onClick, isIntraday }) {
  const isLong    = s.direction === "LONG";
  const accent    = isLong ? "#00c882" : "#ff4659";
  const reachedFTP = s.reached_tp === 4;

  return (
    <div onClick={() => onClick(s)} style={{
      background:"linear-gradient(145deg,#131820,#0e1318)",
      border:`1px solid ${reachedFTP ? "rgba(255,200,0,0.25)" : accent+"22"}`,
      borderRadius:16, padding:18, cursor:"pointer",
      transition:"transform 0.18s,box-shadow 0.18s",
      boxShadow:`0 4px 20px ${accent}0d`,
      position:"relative", overflow:"hidden",
    }}
    onMouseEnter={e=>{e.currentTarget.style.transform="translateY(-2px)";e.currentTarget.style.boxShadow=`0 8px 32px ${accent}22`;}}
    onMouseLeave={e=>{e.currentTarget.style.transform="translateY(0)";e.currentTarget.style.boxShadow=`0 4px 20px ${accent}0d`;}}>

      <div style={{position:"absolute",top:0,right:0,width:70,height:70,
        background:`radial-gradient(circle at top right,${accent}15,transparent)`,pointerEvents:"none"}}/>

      {/* Header */}
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10}}>
        <div>
          <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:2}}>
            <span style={{fontSize:17,fontWeight:900,color:"#fff",letterSpacing:1}}>{s.symbol}</span>
            <span style={{fontSize:10,color:"#555",background:"rgba(255,255,255,0.05)",
              padding:"2px 6px",borderRadius:4,fontFamily:"'DM Mono',monospace"}}>
              {isIntraday ? (s.mode||s.timeframe) : s.timeframe}
            </span>
          </div>
          <div style={{fontSize:11,color:isLong?"#00c882":"#ff4659"}}>{s.role}</div>
        </div>
        <div style={{textAlign:"right"}}>
          <div style={{fontSize:20,fontWeight:900,
            color:s.pnl>=0?"#00c882":"#ff4659",fontFamily:"'DM Mono',monospace"}}>
            {s.pnl>=0?"+":""}{s.pnl}%
          </div>
          <div style={{fontSize:9,color:"#444",marginTop:2}}>累計盈虧</div>
        </div>
      </div>

      {/* Badges */}
      <div style={{display:"flex",gap:6,marginBottom:12,flexWrap:"wrap"}}>
        <DirectionBadge dir={s.direction}/>
        <TypeBadge type={s.signal_type} mode={s.mode}/>
        {s.reached_tp===4 && <FTPBadge/>}
      </div>

      {/* Price Grid */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6,marginBottom:8}}>
        {[
          {label:"觸發價",value:"$"+fmt(s.trigger),color:"#ccc"},
          {label:"當前價",value:s.current?"$"+fmt(s.current):"—",color:"#aaa"},
          {label:"止損 SL",value:"$"+fmt(s.sl),color:"#ff4659"},
          {label:"風險 R",value:s.risk_pct+"%",color:"#ff6b6b"},
        ].map((d,i)=>(
          <div key={i} style={{background:"rgba(255,255,255,0.03)",borderRadius:8,
            padding:"7px 10px",border:"1px solid rgba(255,255,255,0.05)"}}>
            <div style={{fontSize:9,color:"#555",marginBottom:3}}>{d.label}</div>
            <div style={{fontSize:13,fontWeight:700,color:d.color,fontFamily:"'DM Mono',monospace"}}>{d.value}</div>
          </div>
        ))}
      </div>

      {/* TP Row */}
      <div style={{display:"flex",gap:4}}>
        {[s.tp1,s.tp2,s.tp3].map((tp,i)=>{
          const hit = s.reached_tp > i;
          return (
            <div key={i} style={{flex:1,borderRadius:6,padding:"5px 0",textAlign:"center",
              background:hit?"rgba(0,200,130,0.08)":"rgba(255,255,255,0.03)",
              border:`1px solid ${hit?"rgba(0,200,130,0.25)":"rgba(255,255,255,0.06)"}`}}>
              <div style={{fontSize:9,color:hit?"#00c882":"#555",marginBottom:2}}>TP{i+1}</div>
              <div style={{fontSize:10,color:hit?"#00c882":"#888",fontFamily:"'DM Mono',monospace"}}>${fmt(tp)}</div>
            </div>
          );
        })}
        <div style={{flex:1,borderRadius:6,padding:"5px 0",textAlign:"center",
          background:reachedFTP?"rgba(255,200,0,0.1)":"rgba(255,255,255,0.03)",
          border:`1px solid ${reachedFTP?"rgba(255,200,0,0.35)":"rgba(255,255,255,0.06)"}`}}>
          <div style={{fontSize:9,color:"#ffc800",marginBottom:2}}>FTP</div>
          <div style={{fontSize:10,color:"#ffc800",fontFamily:"'DM Mono',monospace"}}>${fmt(s.ftp)}</div>
        </div>
      </div>

      {/* VWAP for intraday */}
      {isIntraday && s.vwap > 0 && (
        <div style={{marginTop:8,padding:"6px 10px",background:"rgba(100,150,255,0.06)",
          borderRadius:6,border:"1px solid rgba(100,150,255,0.15)",
          display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <span style={{fontSize:10,color:"#6496ff"}}>VWAP</span>
          <span style={{fontSize:11,fontWeight:700,color:"#6496ff",fontFamily:"'DM Mono',monospace"}}>${fmt(s.vwap)}</span>
        </div>
      )}

      <div style={{marginTop:8,fontSize:10,color:"#3a3a3a",textAlign:"center"}}>
        觸發於 {s.triggered_at}（{timeAgo(s.timestamp)}）
      </div>
    </div>
  );
}

// ─── Detail Modal ──────────────────────────────────────────
function Modal({ s, onClose, isIntraday }) {
  if (!s) return null;
  const isLong  = s.direction === "LONG";
  const accent  = isLong ? "#00c882" : "#ff4659";

  return (
    <div style={{position:"fixed",inset:0,zIndex:999,background:"rgba(0,0,0,0.88)",
      backdropFilter:"blur(14px)",display:"flex",alignItems:"center",
      justifyContent:"center",padding:16}} onClick={onClose}>
      <div style={{background:"linear-gradient(160deg,#131820,#0d1117)",
        border:`1px solid ${accent}33`,borderRadius:22,padding:24,
        width:"100%",maxWidth:400,boxShadow:`0 32px 96px ${accent}18`,
        animation:"fadeIn 0.2s ease both",overflowY:"auto",maxHeight:"90vh"}}
        onClick={e=>e.stopPropagation()}>

        {/* Header */}
        <div style={{display:"flex",justifyContent:"space-between",marginBottom:16}}>
          <div>
            <div style={{display:"flex",alignItems:"center",gap:8}}>
              <div style={{width:7,height:7,borderRadius:"50%",background:"#00c882",
                boxShadow:"0 0 8px #00c882",animation:"pulse 2s infinite"}}/>
              <span style={{fontSize:11,color:"#555",letterSpacing:1}}>CRYPTO TRADERS CLUB</span>
            </div>
            <div style={{fontSize:10,color:"#3a3a3a",marginTop:2}}>
              {isIntraday ? "日內交易訊號" : "Sentiment Lens · 數據交易訊號"}
            </div>
          </div>
          <button onClick={onClose} style={{background:"rgba(255,255,255,0.06)",
            border:"1px solid rgba(255,255,255,0.08)",color:"#666",
            borderRadius:8,width:30,height:30,cursor:"pointer",fontSize:14}}>✕</button>
        </div>

        {/* Symbol */}
        <div style={{marginBottom:4}}>
          <span style={{fontSize:30,fontWeight:900,color:"#fff",letterSpacing:2}}>{s.symbol}</span>
          <span style={{fontSize:14,color:"#555",marginLeft:10}}>
            {isIntraday ? (s.mode||s.timeframe) : s.timeframe}
          </span>
        </div>
        <div style={{fontSize:12,color:isLong?"#00c882":"#ff4659",marginBottom:14}}>{s.role}</div>

        <div style={{display:"flex",gap:6,marginBottom:16,flexWrap:"wrap"}}>
          <DirectionBadge dir={s.direction}/>
          <TypeBadge type={s.signal_type} mode={s.mode}/>
          {s.reached_tp===4 && <FTPBadge/>}
        </div>

        {/* PnL */}
        <div style={{background:`${accent}0d`,border:`1px solid ${accent}22`,
          borderRadius:12,padding:"14px 18px",marginBottom:12}}>
          <div style={{fontSize:11,color:"#555",marginBottom:4}}>累計盈虧</div>
          <div style={{fontSize:36,fontWeight:900,color:s.pnl>=0?"#00c882":"#ff4659",
            fontFamily:"'DM Mono',monospace",lineHeight:1}}>
            {s.pnl>=0?"+":""}{s.pnl}%
          </div>
        </div>

        {/* Grid */}
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:7,marginBottom:7}}>
          {[
            {l:"觸發價",v:"$"+fmt(s.trigger),c:"#ccc"},
            {l:"當前價",v:s.current?"$"+fmt(s.current):"—",c:"#aaa"},
            {l:"止損 SL",v:"$"+fmt(s.sl),c:"#ff4659"},
            {l:"風險 R",v:s.risk_pct+"%",c:"#ff6b6b"},
            {l:"TP1",v:"$"+fmt(s.tp1),c:"#00c882"},
            {l:"TP2",v:"$"+fmt(s.tp2),c:"#00c882"},
            {l:"TP3",v:"$"+fmt(s.tp3),c:"#00c882"},
            {l:"FTP 👑",v:"$"+fmt(s.ftp),c:"#ffc800",hi:true},
          ].map((d,i)=>(
            <div key={i} style={{background:d.hi?"rgba(255,200,0,0.05)":"rgba(255,255,255,0.03)",
              border:`1px solid ${d.hi?"rgba(255,200,0,0.3)":"rgba(255,255,255,0.06)"}`,
              borderRadius:9,padding:"9px 12px"}}>
              <div style={{fontSize:10,color:"#555",marginBottom:3}}>{d.l}</div>
              <div style={{fontSize:13,fontWeight:700,color:d.c,fontFamily:"'DM Mono',monospace"}}>{d.v}</div>
            </div>
          ))}
        </div>

        {/* Intraday extras */}
        {isIntraday && (
          <div style={{borderTop:"1px solid rgba(255,255,255,0.05)",paddingTop:12,marginBottom:12}}>
            <div style={{fontSize:10,color:"#444",marginBottom:8,letterSpacing:1}}>日內關鍵價位</div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:6}}>
              {[
                {l:"VWAP",v:"$"+fmt(s.vwap),c:"#6496ff"},
                {l:"開盤高",v:"$"+fmt(s.or_high),c:"#00c882"},
                {l:"開盤低",v:"$"+fmt(s.or_low),c:"#ff4659"},
                {l:"流動性高",v:"$"+fmt(s.liq_high),c:"#ffa500"},
                {l:"流動性低",v:"$"+fmt(s.liq_low),c:"#ffa500"},
                {l:"動能",v:(s.momentum>=0?"+":"")+s.momentum+"%",c:s.momentum>=0?"#00c882":"#ff4659"},
              ].map((d,i)=>(
                <div key={i} style={{background:"rgba(255,255,255,0.03)",
                  border:"1px solid rgba(255,255,255,0.05)",borderRadius:8,padding:"7px",textAlign:"center"}}>
                  <div style={{fontSize:9,color:"#444",marginBottom:3}}>{d.l}</div>
                  <div style={{fontSize:11,fontWeight:700,color:d.c,fontFamily:"'DM Mono',monospace"}}>{d.v}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Futures data */}
        <div style={{borderTop:"1px solid rgba(255,255,255,0.05)",paddingTop:12,marginBottom:12}}>
          <div style={{fontSize:10,color:"#444",marginBottom:8,letterSpacing:1}}>期貨數據</div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:6}}>
            {[
              {l:"多空比 LSR",v:s.lsr,c:s.lsr>1?"#00c882":"#ff4659"},
              {l:"資金費率",v:(s.funding>=0?"+":"")+s.funding+"%",c:s.funding>=0?"#ff6b6b":"#00c882"},
              {l:"RSI",v:s.rsi,c:s.rsi>70?"#ff4659":s.rsi<30?"#00c882":"#aaa"},
            ].map((d,i)=>(
              <div key={i} style={{background:"rgba(255,255,255,0.03)",
                border:"1px solid rgba(255,255,255,0.05)",borderRadius:8,padding:"7px",textAlign:"center"}}>
                <div style={{fontSize:9,color:"#444",marginBottom:3}}>{d.l}</div>
                <div style={{fontSize:12,fontWeight:700,color:d.c,fontFamily:"'DM Mono',monospace"}}>{d.v}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Reasons */}
        {s.reasons && s.reasons.length > 0 && (
          <div style={{borderTop:"1px solid rgba(255,255,255,0.05)",paddingTop:12,marginBottom:12}}>
            <div style={{fontSize:10,color:"#444",marginBottom:8,letterSpacing:1}}>觸發條件</div>
            {s.reasons.map((r,i)=>(
              <div key={i} style={{display:"flex",alignItems:"center",gap:8,marginBottom:5}}>
                <div style={{width:5,height:5,borderRadius:"50%",
                  background:s.direction==="LONG"?"#00c882":"#ff4659",flexShrink:0}}/>
                <span style={{fontSize:11,color:"#888"}}>{r}</span>
              </div>
            ))}
          </div>
        )}

        <div style={{fontSize:10,color:"#333",textAlign:"center"}}>
          觸發於 {s.triggered_at}（{timeAgo(s.timestamp)}）
        </div>
      </div>
    </div>
  );
}

// ─── Stats Bar ─────────────────────────────────────────────
function StatsBar({ data, isIntraday }) {
  const signals = data?.signals || [];
  const longs   = signals.filter(s=>s.direction==="LONG").length;
  const shorts  = signals.filter(s=>s.direction==="SHORT").length;
  const ftp     = signals.filter(s=>s.reached_tp===4).length;
  const active  = data?.active_count || signals.filter(s=>s.active!==false).length;
  const wr      = data?.win_rate || 0;

  return (
    <div style={{display:"flex",gap:10,flexWrap:"wrap",marginBottom:20}}>
      {[
        {l:"總訊號",v:signals.length,c:"#aaa"},
        {l:"活躍中",v:active,c:"#00c882"},
        {l:"做多",v:longs,c:"#00c882"},
        {l:"做空",v:shorts,c:"#ff4659"},
        {l:"👑 FTP",v:ftp,c:"#ffc800"},
        {l:"勝率",v:wr+"%",c:wr>=60?"#00c882":wr>=50?"#ffc800":"#ff4659"},
      ].map((s,i)=>(
        <div key={i} style={{background:"rgba(255,255,255,0.03)",
          border:"1px solid rgba(255,255,255,0.06)",borderRadius:10,
          padding:"9px 14px",textAlign:"center"}}>
          <div style={{fontSize:18,fontWeight:900,color:s.c,fontFamily:"'DM Mono',monospace"}}>{s.v}</div>
          <div style={{fontSize:10,color:"#555",marginTop:2}}>{s.l}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Filter Bar ────────────────────────────────────────────
function FilterBar({ dir, setDir, tf, setTf, reachedOnly, setReachedOnly,
                     search, setSearch, isIntraday, mode, setMode }) {
  const btn = (active, label, onClick, color) => (
    <button key={label} onClick={onClick} style={{
      padding:"5px 12px",borderRadius:7,fontSize:11,fontWeight:active?700:400,
      cursor:"pointer",border:`1px solid ${active?"rgba(255,255,255,0.18)":"rgba(255,255,255,0.07)"}`,
      background:active?"rgba(255,255,255,0.09)":"transparent",
      color:active?(color||"#ddd"):"#555",transition:"all 0.15s",
    }}>{label}</button>
  );

  const tfs = isIntraday ? ["ALL","超短線","短線","半日"] : ["ALL","15M","1H","4H"];

  return (
    <div style={{display:"flex",gap:7,flexWrap:"wrap",marginBottom:18,alignItems:"center"}}>
      <input value={search} onChange={e=>setSearch(e.target.value.toUpperCase())}
        placeholder="搜尋幣種..." style={{
          background:"rgba(255,255,255,0.04)",border:"1px solid rgba(255,255,255,0.08)",
          borderRadius:7,padding:"5px 11px",color:"#ccc",fontSize:12,
          outline:"none",width:110,fontFamily:"'DM Mono',monospace",
        }}/>
      <div style={{width:1,height:18,background:"rgba(255,255,255,0.07)"}}/>
      {[["ALL","全部"],["LONG","做多","#00c882"],["SHORT","做空","#ff4659"]].map(([d,l,c])=>
        btn(dir===d,l,()=>setDir(d),c)
      )}
      <div style={{width:1,height:18,background:"rgba(255,255,255,0.07)"}}/>
      {tfs.map(t=>btn(tf===t,t==="ALL"?"全部週期":t,()=>setTf(t)))}
      <div style={{width:1,height:18,background:"rgba(255,255,255,0.07)"}}/>
      {btn(reachedOnly,"👑 FTP",()=>setReachedOnly(!reachedOnly),"#ffc800")}
    </div>
  );
}

// ─── Page: Sentiment (波段) ────────────────────────────────
function SentimentPage() {
  const [data,         setData]         = useState(null);
  const [loading,      setLoading]      = useState(true);
  const [lastUpdate,   setLastUpdate]   = useState("");
  const [selected,     setSelected]     = useState(null);
  const [dirFilter,    setDirFilter]    = useState("ALL");
  const [tfFilter,     setTfFilter]     = useState("ALL");
  const [reachedOnly,  setReachedOnly]  = useState(false);
  const [search,       setSearch]       = useState("");
  const [error,        setError]        = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/signals?" + Date.now(), {
        mode:"cors", headers:{"Accept":"application/json"}
      });
      if (!res.ok) throw new Error("無法載入訊號");
      const d = await res.json();
      setData(d);
      setLastUpdate(d.updated_at || "");
      setError(null);
    } catch(e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const signals = data?.signals || [];
  const filtered = signals.filter(s => {
    if (search && !s.symbol.includes(search)) return false;
    if (dirFilter !== "ALL" && s.direction !== dirFilter) return false;
    if (tfFilter !== "ALL" && s.timeframe !== tfFilter) return false;
    if (reachedOnly && s.reached_tp !== 4) return false;
    return true;
  });

  return (
    <div>
      <div style={{marginBottom:22}}>
        <h1 style={{fontSize:24,fontWeight:900,color:"#fff",marginBottom:4}}>數據交易訊號</h1>
        <p style={{fontSize:12,color:"#555"}}>基於資金費率・多空比・三燈系統的波段訊號</p>
      </div>
      {error && (
        <div style={{background:"rgba(255,70,89,0.08)",border:"1px solid rgba(255,70,89,0.2)",
          borderRadius:10,padding:"12px 16px",marginBottom:16,fontSize:12,color:"#ff6b6b"}}>
          ⚠️ {error}
        </div>
      )}
      {data && <StatsBar data={data}/>}
      <FilterBar dir={dirFilter} setDir={setDirFilter} tf={tfFilter} setTf={setTfFilter}
        reachedOnly={reachedOnly} setReachedOnly={setReachedOnly}
        search={search} setSearch={setSearch} isIntraday={false}/>
      {loading ? (
        <div style={{textAlign:"center",padding:"60px 0",color:"#444"}}>
          <div style={{fontSize:36,marginBottom:12}}>⏳</div>
          <div>載入中...</div>
        </div>
      ) : filtered.length === 0 ? (
        <div style={{textAlign:"center",padding:"60px 0",color:"#444"}}>
          <div style={{fontSize:36,marginBottom:12}}>📭</div>
          <div>目前沒有符合條件的訊號</div>
        </div>
      ) : (
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(290px,1fr))",gap:14}}>
          {filtered.map((s,i) => (
            <div key={s.id} style={{animation:"fadeIn 0.3s ease both",animationDelay:i*0.02+"s"}}>
              <SignalCard s={s} onClick={setSelected} isIntraday={false}/>
            </div>
          ))}
        </div>
      )}
      {selected && <Modal s={selected} onClose={()=>setSelected(null)} isIntraday={false}/>}
    </div>
  );
}

// ─── Page: Intraday (日內) ─────────────────────────────────
function IntradayPage() {
  const [data,         setData]         = useState(null);
  const [loading,      setLoading]      = useState(true);
  const [selected,     setSelected]     = useState(null);
  const [dirFilter,    setDirFilter]    = useState("ALL");
  const [tfFilter,     setTfFilter]     = useState("ALL");
  const [reachedOnly,  setReachedOnly]  = useState(false);
  const [search,       setSearch]       = useState("");
  const [error,        setError]        = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/intraday?" + Date.now(), {
        mode:"cors", headers:{"Accept":"application/json"}
      });
      if (!res.ok) throw new Error("無法載入日內訊號");
      const d = await res.json();
      setData(d);
      setError(null);
    } catch(e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  const signals = data?.signals || [];
  const filtered = signals.filter(s => {
    if (search && !s.symbol.includes(search)) return false;
    if (dirFilter !== "ALL" && s.direction !== dirFilter) return false;
    if (tfFilter !== "ALL" && (s.mode||s.timeframe) !== tfFilter) return false;
    if (reachedOnly && s.reached_tp !== 4) return false;
    return true;
  });

  return (
    <div>
      <div style={{marginBottom:22}}>
        <h1 style={{fontSize:24,fontWeight:900,color:"#fff",marginBottom:4}}>日內交易訊號</h1>
        <p style={{fontSize:12,color:"#555"}}>VWAP・開盤區間・流動性掃描・超短線/短線/半日</p>
      </div>

      {/* Session indicator */}
      <SessionIndicator/>

      {error && (
        <div style={{background:"rgba(255,70,89,0.08)",border:"1px solid rgba(255,70,89,0.2)",
          borderRadius:10,padding:"12px 16px",marginBottom:16,fontSize:12,color:"#ff6b6b"}}>
          ⚠️ {error}
        </div>
      )}
      {data && <StatsBar data={data} isIntraday/>}
      <FilterBar dir={dirFilter} setDir={setDirFilter} tf={tfFilter} setTf={setTfFilter}
        reachedOnly={reachedOnly} setReachedOnly={setReachedOnly}
        search={search} setSearch={setSearch} isIntraday/>
      {loading ? (
        <div style={{textAlign:"center",padding:"60px 0",color:"#444"}}>
          <div style={{fontSize:36,marginBottom:12}}>⏳</div>
          <div>載入中...</div>
        </div>
      ) : filtered.length === 0 ? (
        <div style={{textAlign:"center",padding:"60px 0",color:"#444"}}>
          <div style={{fontSize:36,marginBottom:12}}>📭</div>
          <div>目前沒有日內訊號</div>
          <div style={{fontSize:12,color:"#333",marginTop:8}}>建議在歐洲盤或美洲盤時段查看</div>
        </div>
      ) : (
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(290px,1fr))",gap:14}}>
          {filtered.map((s,i) => (
            <div key={s.id} style={{animation:"fadeIn 0.3s ease both",animationDelay:i*0.02+"s"}}>
              <SignalCard s={s} onClick={setSelected} isIntraday/>
            </div>
          ))}
        </div>
      )}
      {selected && <Modal s={selected} onClose={()=>setSelected(null)} isIntraday/>}
    </div>
  );
}

// ─── Session Indicator ─────────────────────────────────────
function SessionIndicator() {
  const [session, setSession] = useState("");
  useEffect(() => {
    const update = () => {
      const h = (new Date().getUTCHours() + 8) % 24;
      if (h >= 8  && h < 16)  setSession("亞洲盤 🟡");
      else if (h >= 15 && h < 22) setSession("歐洲盤 🟢 高流動性");
      else if (h >= 20 || h < 4)  setSession("美洲盤 🟢 高流動性");
      else setSession("離市時段 ⚪");
    };
    update();
    const id = setInterval(update, 60000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:16,
      padding:"8px 14px",background:"rgba(255,255,255,0.03)",
      borderRadius:8,border:"1px solid rgba(255,255,255,0.06)",width:"fit-content"}}>
      <span style={{fontSize:11,color:"#555"}}>當前時段：</span>
      <span style={{fontSize:12,fontWeight:700,color:"#ddd"}}>{session}</span>
    </div>
  );
}

// ─── Main App ──────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState("sentiment");

  const navBtn = (id, label, icon) => (
    <button onClick={()=>setPage(id)} style={{
      display:"flex",alignItems:"center",gap:6,
      padding:"8px 16px",borderRadius:8,cursor:"pointer",
      border:`1px solid ${page===id?"rgba(0,200,130,0.4)":"rgba(255,255,255,0.08)"}`,
      background:page===id?"rgba(0,200,130,0.1)":"transparent",
      color:page===id?"#00c882":"#666",fontSize:13,fontWeight:page===id?700:400,
      transition:"all 0.2s",
    }}>
      <span>{icon}</span> {label}
    </button>
  );

  return (
    <div style={{minHeight:"100vh",background:"#080c10",color:"#e8e8e8",
      fontFamily:"'Noto Sans TC',-apple-system,sans-serif"}}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Noto+Sans+TC:wght@400;700;900&display=swap');
        *{box-sizing:border-box;margin:0;padding:0;}
        ::-webkit-scrollbar{width:5px}
        ::-webkit-scrollbar-track{background:#080c10}
        ::-webkit-scrollbar-thumb{background:#1e2530;border-radius:3px}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
        @keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
      `}</style>

      {/* Navbar */}
      <div style={{borderBottom:"1px solid rgba(255,255,255,0.05)",
        background:"rgba(8,12,16,0.97)",backdropFilter:"blur(20px)",
        position:"sticky",top:0,zIndex:100,padding:"0 24px"}}>
        <div style={{maxWidth:1200,margin:"0 auto",height:58,
          display:"flex",alignItems:"center",justifyContent:"space-between"}}>

          {/* Logo */}
          <div style={{display:"flex",alignItems:"center",gap:10}}>
            <div style={{width:32,height:32,borderRadius:9,
              background:"linear-gradient(135deg,#00c882,#005540)",
              display:"flex",alignItems:"center",justifyContent:"center",
              fontSize:16,boxShadow:"0 0 12px rgba(0,200,130,0.3)"}}>⚡</div>
            <div>
              <div style={{fontSize:12,fontWeight:900,color:"#fff",letterSpacing:1}}>CRYPTO TRADERS CLUB</div>
              <div style={{fontSize:9,color:"#444"}}>Sentiment Lens</div>
            </div>
          </div>

          {/* Nav tabs */}
          <div style={{display:"flex",gap:8}}>
            {navBtn("sentiment","波段訊號","📊")}
            {navBtn("intraday","日內交易","⚡")}
          </div>

          {/* Live dot */}
          <div style={{display:"flex",alignItems:"center",gap:6}}>
            <div style={{width:7,height:7,borderRadius:"50%",background:"#00c882",
              boxShadow:"0 0 8px #00c882",animation:"pulse 2s infinite"}}/>
            <span style={{fontSize:11,color:"#555"}}>即時更新</span>
          </div>
        </div>
      </div>

      {/* Body */}
      <div style={{maxWidth:1200,margin:"0 auto",padding:"28px 24px"}}>
        {page === "sentiment" ? <SentimentPage/> : <IntradayPage/>}
      </div>

      {/* Footer */}
      <div style={{textAlign:"center",padding:"24px",
        borderTop:"1px solid rgba(255,255,255,0.04)",marginTop:40}}>
        <div style={{fontSize:10,color:"#2a2a2a"}}>cryptotradersclub.org/sentiment</div>
        <div style={{fontSize:10,color:"#1e1e1e",marginTop:4}}>
          本平台訊號僅供參考，不構成投資建議。交易有風險，入市需謹慎。
        </div>
      </div>
    </div>
  );
}
