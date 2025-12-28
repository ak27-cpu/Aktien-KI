import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. SETUP & BASIS ---
st.set_page_config(page_title="Investment Cockpit v21 - Basis", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Setup Fehler: {e}")
    st.stop()

# --- 2. KI FUNKTION FÜR FAIR VALUE ---
def get_ai_fair_value(ticker, info, cp):
    prompt = f"Gib NUR den fairen Wert für {ticker} als Zahl zurück. Aktueller Preis: {cp}, KGV: {info.get('trailingPE')}."
    try:
        response = ki_model.generate_content(prompt)
        val = "".join(c for c in response.text if c.isdigit() or c == '.')
        return float(val)
    except: return cp * 0.95

# --- 3. DATEN-ENGINE ---
@st.cache_data(ttl=1800)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="3y")
        if h.empty: return None
        info = s.info
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        
        # Korrektur-Statistik
        roll_max = h['High'].cummax()
        avg_dd = round(((h['Low'] - roll_max) / roll_max).mean() * 100, 2)

        # RSI
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "ATH_Dist": round(((cp / ath) - 1) * 100, 1),
            "Avg_Korr": avg_dd,
            "RSI": round(rsi, 1),
            "Trend": "Bull 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Bear 📉",
            "KGV": info.get('trailingPE', 0),
            "raw_info": info
        }
    except: return None

# --- 4. HEADER & MARKT ---
vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
st.title("🏛️ Professional Strategy Cockpit")
st.metric("VIX (Marktangst)", f"{round(vix, 2)}")
st.divider()

# --- 5. DATENVERARBEITUNG ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    m_data = []
    with st.spinner("Berechne Strategie-Zonen..."):
        for _, r in df_db.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                # Fair Value Logik
                db_fv = r.get('fair_value')
                fv = float(db_fv) if db_fv and db_fv > 0 else get_ai_fair_value(r['ticker'], m['raw_info'], m['Preis'])
                
                # Tranchen Logik (Basierend auf ATH)
                t1 = m['ATH'] * 0.90  # -10%
                t2 = m['ATH'] * 0.80  # -20%
                
                # Bewertung für Strategie-Check
                rating = "Überbewertet 🔴"
                if m['Preis'] <= fv: rating = "Fair bewertet 🟡"
                if m['RSI'] < 35 or m['ATH_Dist'] < m['Avg_Korr']: rating = "KAUFZONE 🟢"

                m_data.append({
                    "Ticker": r['ticker'], "Name": m['Name'], "Sektor": m['Sektor'],
                    "Kurs": m['Preis'], "Fair Value": round(fv, 2),
                    "Tranche 1 (-10%)": round(t1, 2), "Tranche 2 (-20%)": round(t2, 2),
                    "Korr %": m['ATH_Dist'], "Ø Korr %": m['Avg_Korr'],
                    "RSI": m['RSI'], "Trend": m['Trend'], "Bewertung": rating
                })

    if m_data:
        df = pd.DataFrame(m_data)
        tab1, tab2, tab3 = st.tabs(["📊 Marktsituation", "🎯 Technische Indikatoren", "🚀 Strategie-Check"])
        
        with tab1:
            st.dataframe(df[["Ticker", "Name", "Sektor", "Kurs", "Fair Value"]], use_container_width=True, hide_index=True)

        with tab2:
            st.dataframe(df[["Ticker", "Korr %", "Ø Korr %", "Trend", "RSI"]], use_container_width=True, hide_index=True)

        with tab3:
            st.subheader("Kaufzonen & Einstiegs-Logik")
            # Übersicht über Kurs, FV, Korrekturen und das finale Rating
            st.dataframe(df[["Ticker", "Kurs", "Fair Value", "Korr %", "Ø Korr %", "RSI", "Bewertung"]].style.apply(
                lambda x: ['background-color: #004d00' if "🟢" in str(x.Bewertung) else '' for i in x], axis=1),
                use_container_width=True, hide_index=True)
            
            st.info("💡 Kaufzone (🟢) wird erreicht, wenn der RSI < 35 ist ODER die aktuelle Korrektur größer als der historische Durchschnitt ist.")

# Sidebar Refresh
with st.sidebar:
    if st.button("🔄 Refresh All"):
        st.cache_data.clear()
        st.rerun()
