import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit v20", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Verbindungsfehler: {e}")
    st.stop()

# --- 2. MARKT-INDIKATOREN ---
def get_market_indicators():
    try:
        vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        spy = yf.Ticker("^GSPC").history(period="300d")
        cp = spy['Close'].iloc[-1]
        sma125 = spy['Close'].rolling(125).mean().iloc[-1]
        fg_score = int((cp / sma125) * 50)
        return round(vix, 2), min(100, fg_score)
    except: return 20.0, 50

@st.cache_data(ttl=1800)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="3y")
        if h.empty: return None
        info = s.info
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        
        # Historische Korrekturanalyse
        roll_max = h['High'].cummax()
        drawdown = (h['Low'] - roll_max) / roll_max
        avg_dd = round(drawdown.mean() * 100, 2)

        # RSI
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + (gain / loss)))

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH_Dist": round(((cp / ath) - 1) * 100, 1),
            "Avg_Korr": avg_dd,
            "RSI": round(rsi.iloc[-1], 1),
            "Trend": "Bull 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Bear 📉",
            "KGV": info.get('trailingPE', 0),
            "Div": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0
        }
    except: return None

# --- 3. DATEN LADEN ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

# --- 4. HEADER (MARKT-SITUATION) ---
vix, fg = get_market_indicators()
st.title("🏛️ Professional Investment Cockpit")

c1, c2 = st.columns(2)
c1.metric("VIX (Angst)", vix, delta="Vola" if vix > 20 else "Ruhig", delta_color="inverse")
c2.metric("Fear & Greed (Gier)", f"{fg}/100", delta="Gier" if fg > 50 else "Angst")

st.divider()

# --- 5. ANALYSE-BEREICHE ---
if not df_db.empty:
    m_data = []
    with st.spinner("Lade alle Aktien-Metriken..."):
        for _, r in df_db.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                fv = float(r['fair_value']) if r.get('fair_value') else 0.0
                m_data.append({**m, "Ticker": r['ticker'], "Fair Value": fv})

    if m_data:
        df = pd.DataFrame(m_data)

        # DIE DREI UNTERTEILUNGEN
        tab1, tab2, tab3 = st.tabs(["📊 Marktsituation", "🎯 Technische Indikatoren", "🤖 KI Strategie-Check"])
        
        with tab1:
            st.subheader("Aktuelle Marktübersicht")
            # Zeigt Ticker, Name, Sektor, Kurs und Fair Value
            st.dataframe(df[["Ticker", "Name", "Sektor", "Preis", "Fair Value", "KGV", "Div"]], use_container_width=True, hide_index=True)

        with tab2:
            st.subheader("Technische Einstiegshilfen")
            # Zeigt Korrektur vom ATH, Ø Korrektur, Trend, RSI
            st.dataframe(df[["Ticker", "ATH_Dist", "Avg_Korr", "Trend", "RSI"]].sort_values("ATH_Dist"), use_container_width=True, hide_index=True)

        with tab3:
            st.subheader("KI Deep-Dive & Entscheidung")
            sel_ticker = st.selectbox("Aktie wählen:", df['Ticker'].tolist())
            if st.button("Analyse durchführen"):
                d = next(item for item in m_data if item["Ticker"] == sel_ticker)
                prompt = f"""Analysiere {sel_ticker}. Sektor: {d['Sektor']}, RSI: {d['RSI']}, 
                Korrektur: {d['ATH_Dist']}% (Ø: {d['Avg_Korr']}%), Trend: {d['Trend']}. 
                Sollte man Warten, Halten, Kaufen oder Nachkaufen? 
                Gib 3 kurze, prägnante Gründe basierend auf den Daten."""
                
                with st.chat_message("assistant"):
                    st.write(ki_model.generate_content(prompt).text)
    
    # Refresh-Button am Ende der Sidebar
    with st.sidebar:
        if st.button("🔄 Alle Daten aktualisieren"):
            st.cache_data.clear()
            st.rerun()
else:
    st.info("Keine Aktien in der Datenbank gefunden.")
