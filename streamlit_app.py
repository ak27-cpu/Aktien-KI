import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP & KONFIGURATION ---
st.set_page_config(page_title="Investment Cockpit 2025", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Setup Fehler: {e}")
    st.stop()

# --- 2. MARKT-INDIKATOREN (VIX & FEAR/GREED) ---
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
def get_full_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="2y")
        if h.empty: return None
        
        info = s.info
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        vol = h['Volume'].iloc[-1] # Aktuelles Tagesvolumen
        
        # SMA 200 Trend
        sma200 = h['Close'].rolling(window=200).mean().iloc[-1]
        trend = "Bullish 📈" if cp > sma200 else "Bearish 📉"
        
        # RSI 14
        delta = h['Close'].diff()
        g = delta.where(delta > 0, 0).rolling(14).mean()
        l = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (g/l))).iloc[-1]
        
        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "RSI": round(rsi, 1),
            "Trend": trend,
            "Volumen": vol,
            "Korrektur_ATH": round(((cp/ath)-1)*100, 1)
        }
    except: return None

# --- 3. HEADER & BANNER ---
vix, fg = get_market_indicators()
st.title("🏛️ Professional Investment Cockpit")

c1, c2 = st.columns(2)
with c1:
    if vix < 20: st.success(f"📉 VIX: {vix} (Ruhig)")
    elif vix < 30: st.warning(f"⚠️ VIX: {vix} (Nervös)")
    else: st.error(f"🚨 VIX: {vix} (PANIK)")
with c2:
    if fg < 35: st.success(f"😱 Fear & Greed: {fg}/100 (Angst = KAUFCHANCE)")
    elif fg < 70: st.info(f"⚖️ Fear & Greed: {fg}/100 (Neutral)")
    else: st.error(f"🔥 Fear & Greed: {fg}/100 (Gier = VORSICHT)")

st.divider()

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Strategie & MoS")
    base_mos = st.slider("Basis Margin of Safety (%)", 0, 50, 15)
    t1_drop = st.slider("Tranche 1 (Korr. vom ATH %)", 5, 50, 15)
    t2_drop = st.slider("Tranche 2 (Korr. vom ATH %)", 10, 70, 30)
    
    # Dynamische MoS Anpassung
    mos_adj = 10 if fg > 70 else (-5 if fg < 30 else 0)
    total_mos = base_mos + mos_adj
    st.info(f"Gesamt-MoS: {total_mos}%")
    
    if st.button("🔄 Alle Daten aktualisieren"):
        st.cache_data.clear()
        st.rerun()

# --- 5. DATENVERARBEITUNG ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    market_data = []
    strat_data = []
    
    with st.spinner("Synchronisiere Live-Daten..."):
        for _, r in df_db.iterrows():
            m = get_full_metrics(r['ticker'])
            if m:
                # Logik für Tabelle 2
                fv_basis = r.get('fair_value', 0)
                adjusted_fv = fv_basis * (1 - (total_mos / 100))
                t1_p = m['ATH'] * (1 - t1_drop/100)
                t2_p = m['ATH'] * (1 - t2_drop/100)
                
                # Tabelle 1: Basis Daten
                market_data.append({
                    "Ticker": r['ticker'],
                    "Name": m['Name'],
                    "Sektor": m['Sektor'],
                    "Kurs": m['Preis'],
                    "RSI": m['RSI'],
                    "Trend": m['Trend'],
                    "Korr/ATH %": m['Korrektur_ATH'],
                    "Volumen (Stk)": f"{m['Volumen']:,}"
                })
                
                # Tabelle 2: Strategische Bewertung
                status = "⏳ Warten"
                if m['Preis'] <= adjusted_fv and m['Preis'] <= t1_p: status = "🎯 TR1 BEREIT"
                if m['Preis'] <= t2_p: status = "🔥 TR2 LIMIT"
                
                strat_data.append({
                    "Ticker": r['ticker'],
                    "Fair Value (Basis)": fv_basis,
                    "Fair Value (MoS)": round(adjusted_fv, 2),
                    "Tranche 1 Preis": round(t1_p, 2),
                    "Tranche 2 Preis": round(t2_p, 2),
                    "Bewertung": status
                })

    # --- ANZEIGE TABELLE 1 ---
    st.subheader("1️⃣ Basis Marktdaten & Volumen")
    st.dataframe(pd.DataFrame(market_data), use_container_width=True, hide_index=True)

    # --- ANZEIGE TABELLE 2 ---
    st.subheader("2️⃣ Strategische Bewertung & Tranchen")
    
    def style_eval(v):
        if "🎯" in v: return 'background-color: #004d00; color: white'
        if "🔥" in v: return 'background-color: #800000; color: white'
        return ''
    
    st.dataframe(pd.DataFrame(strat_data).style.applymap(style_eval, subset=['Bewertung']), 
                 use_container_width=True, hide_index=True)

    # --- 6. KI ANALYSE ---
    st.divider()
    sel_ticker = st.selectbox("KI Deep-Dive Analyse:", [d['Ticker'] for d in market_data])
    if st.button("Analyse-Prozess starten"):
        m_ctx = next(item for item in market_data if item["Ticker"] == sel_ticker)
        s_ctx = next(item for item in strat_data if item["Ticker"] == sel_ticker)
        
        prompt = f"""Analysiere {sel_ticker} ({m_ctx['Name']}). 
        Marktkontext: VIX {vix}, Fear&Greed {fg}.
        Technik: RSI {m_ctx['RSI']}, Trend {m_ctx['Trend']}, Korrektur vom ATH {m_ctx['Korr/ATH %']}.
        Bewertung: Fair Value Basis {s_ctx['Fair Value (Basis)']}, MoS-Ziel {s_ctx['Fair Value (MoS)']}.
        Berücksichtige das Volumen von {m_ctx['Volumen (Stk)']} für die Bestätigung des Trends."""
        
        with st.chat_message("assistant"):
            st.markdown(ki_model.generate_content(prompt).text)

else:
    st.info("Datenbank ist leer. Bitte Ticker in Supabase hinzufügen.")
