import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit v18", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Verbindungsfehler: {e}")
    st.stop()

# --- 2. MARKT-INDIKATOREN (VIX, F&G, S&P 1J) ---
def get_market_indicators():
    try:
        vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        spy = yf.Ticker("^GSPC").history(period="300d")
        cp = spy['Close'].iloc[-1]
        sma125 = spy['Close'].rolling(125).mean().iloc[-1]
        fg_score = int((cp / sma125) * 50)
        return round(vix, 2), min(100, fg_score), round(spy_1y, 2)
    except: return 20.0, 50, 0.0

@st.cache_data(ttl=1800)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="3y")
        if h.empty: return None
        info = s.info
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        
        # Durchschnittliche Korrektur (Drawdown)
        roll_max = h['High'].cummax()
        drawdown = (h['Low'] - roll_max) / roll_max
        avg_dd = round(drawdown.mean() * 100, 2)

        # RSI Berechnung
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH_Dist": round(((cp / ath) - 1) * 100, 1),
            "Avg_Korr": avg_dd,
            "RSI": round(rsi.iloc[-1], 1),
            "Trend": "Bull 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Bear 📉",
            "KGV": info.get('trailingPE', 0),
            "Div": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0,
            "raw_info": info
        }
    except: return None

def get_ai_rating(ticker, m):
    prompt = f"""Analysiere {ticker} ({m['Name']}). Sektor: {m['Sektor']}, RSI: {m['RSI']}, Korrektur vom ATH: {m['ATH_Dist']}%, Ø Korrektur: {m['Avg_Korr']}%, Trend: {m['Trend']}.
    Gib eine kurze Einschätzung: Warten, Halten, Kaufen oder Nachkaufen? Begründe kurz nach Value-Kriterien."""
    try:
        return ki_model.generate_content(prompt).text
    except: return "Analyse derzeit nicht verfügbar."

# --- 3. DATEN LADEN & SIDEBAR ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

with st.sidebar:
    st.header("📂 Cockpit Steuerung")
    view = st.radio("Fokus:", ["Alle Aktien", "Tranche Strategie", "Sparplan Liste"])
    st.divider()
    if st.button("🔄 Daten aktualisieren"):
        st.cache_data.clear()
        st.rerun()

# --- 4. HEADER (MARKT-SITUATION) ---
vix, fg, spy_1y = get_market_indicators()
st.title("🏛️ Professional Investment Cockpit")

# Die drei gewünschten Marktmetriken im Header
c1, c2, c3 = st.columns(3)
c1.metric("VIX (Volatilität)", vix, "Angst-Index")
c2.metric("Fear & Greed (est.)", f"{fg}/100", "Marktstimmung")
c3.metric("S&P 500 (1 Jahr)", f"{spy_1y}%", "Index Performance")

st.divider()

# --- 5. ANALYSE-BEREICH ---
if not df_db.empty:
    df_filtered = df_db if "Alle" in view else df_db[df_db['watchlist_type'].str.lower() == view.split()[0].lower()]
    
    m_data = []
    with st.spinner("Synchronisiere Markt- und KI-Daten..."):
        for _, r in df_filtered.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                # Fair Value Logik (Manuell aus DB oder 0)
                fv = float(r['fair_value']) if r.get('fair_value') else 0.0
                m_data.append({**m, "Ticker": r['ticker'], "Fair Value": fv})

    if m_data:
        df = pd.DataFrame(m_data)

        # TAB 1: AKTUELLE MARKT SITUATION
        # (Ticker, Name, Sektor, Kurs, Fair Value)
        tab1, tab2, tab3 = st.tabs(["📊 Marktsituation", "🎯 Technische Indikatoren", "🤖 KI Strategie-Check"])
        
        with tab1:
            st.dataframe(df[["Ticker", "Name", "Sektor", "Preis", "Fair Value", "KGV", "Div"]], use_container_width=True, hide_index=True)

        # TAB 2: TECHNISCHE INDIKATOREN
        # (Korrektur ATH, Ø Korrektur, Trend, RSI)
        with tab2:
            st.dataframe(df[["Ticker", "ATH_Dist", "Avg_Korr", "Trend", "RSI"]], use_container_width=True, hide_index=True)

        # TAB 3: KI EINSCHÄTZUNG
        with tab3:
            sel_ticker = st.selectbox("Wähle einen Ticker für den Deep-Dive:", df['Ticker'].tolist())
            if st.button("KI Analyse starten"):
                stock_data = next(item for item in m_data if item["Ticker"] == sel_ticker)
                with st.chat_message("assistant"):
                    st.write(get_ai_rating(sel_ticker, stock_data))
else:
    st.info("Keine Daten in der Datenbank gefunden.")
