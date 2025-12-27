import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP & KONFIGURATION ---
st.set_page_config(page_title="Investment Terminal 2025 Pro", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Setup Fehler: {e}")
    st.stop()

# --- 2. MARKT-INDIKATOREN ---
def get_market_indicators():
    try:
        vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        spy = yf.Ticker("^GSPC").history(period="150d")
        cp = spy['Close'].iloc[-1]
        sma125 = spy['Close'].rolling(125).mean().iloc[-1]
        fg_score = int((cp / sma125) * 50)
        return round(vix, 2), min(100, fg_score)
    except: return 20.0, 50

@st.cache_data(ttl=1800)
def get_extended_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="2y")
        if h.empty: return None
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        
        # Trend: 200-Tage-Linie
        sma200 = h['Close'].rolling(window=200).mean().iloc[-1]
        trend = "Bullish 📈" if cp > sma200 else "Bearish 📉"
        
        # RSI 14
        delta = h['Close'].diff()
        g = delta.where(delta > 0, 0).rolling(14).mean()
        l = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (g/l))).iloc[-1]
        
        return {"Preis": round(cp, 2), "ATH": round(ath, 2), "RSI": round(rsi, 1), "SMA200": round(sma200, 2), "Trend": trend}
    except: return None

# --- 3. HEADER & BANNER ---
vix, fg = get_market_indicators()
st.title("🏛️ Investment Cockpit Pro")
c1, c2 = st.columns(2)
with c1:
    if vix < 20: st.success(f"📉 VIX: {vix} (Ruhig)")
    elif vix < 30: st.warning(f"⚠️ VIX: {vix} (Nervös)")
    else: st.error(f"🚨 VIX: {vix} (PANIK)")
with c2:
    if fg < 35: st.success(f"😱 Fear & Greed: {fg}/100 (Kaufchance)")
    elif fg < 70: st.info(f"⚖️ Fear & Greed: {fg}/100 (Neutral)")
    else: st.error(f"🔥 Fear & Greed: {fg}/100 (Gier - Vorsicht)")
st.divider()

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Strategie")
    base_mos = st.slider("Basis MoS (%)", 0, 50, 15)
    t1_drop = st.slider("Tranche 1 (ATH-Korr %)", 5, 50, 15)
    rsi_limit = st.slider("Max. RSI für Kauf", 20, 70, 45)
    
    # Dynamische MoS Anpassung
    mos_adj = 10 if fg > 70 else (-5 if fg < 30 else 0)
    total_mos = base_mos + mos_adj
    st.info(f"Gesamt-MoS: {total_mos}%")
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# --- 5. WATCHLIST ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    rows = []
    for _, r in df_db.iterrows():
        m = get_extended_metrics(r['ticker'])
        if m:
            fv_adj = r['fair_value'] * (1 - total_mos/100)
            t1_p = m['ATH'] * (1 - t1_drop/100)
            
            status = "⏳ Warten"
            if m['Preis'] <= fv_adj and m['Preis'] <= t1_p:
                status = "🎯 KAUFZONE" if m['RSI'] <= rsi_limit else "⚠️ RSI HOCH"
            
            rows.append({
                "Ticker": r['ticker'], "Kurs": m['Preis'], "MoS-FV": round(fv_adj, 2),
                "Trend": m['Trend'], "RSI": m['RSI'], "Status": status, "Korr/ATH": f"{round(((m['Preis']/m['ATH'])-1)*100, 1)}%"
            })

    df_f = pd.DataFrame(rows)
    def style_stat(v):
        if "🎯" in v: return 'background-color: #004d00'
        if "⚠️" in v: return 'background-color: #4d4d00'
        return ''
    
    st.dataframe(df_f.style.applymap(style_stat, subset=['Status']), use_container_width=True, hide_index=True)

    # --- 6. KI ANALYSE ---
    st.divider()
    sel = st.selectbox("Deep Dive:", df_f['Ticker'])
    if st.button("Experten-Check"):
        ctx = df_f[df_f['Ticker'] == sel].iloc[0].to_dict()
        prompt = f"Analysiere {sel}. Markt: VIX {vix}, F&G {fg}. Trend ist {ctx['Trend']}. FV-MoS: {ctx['MoS-FV']}. Fazit?"
        with st.chat_message("assistant"):
            st.markdown(ki_model.generate_content(prompt).text)
