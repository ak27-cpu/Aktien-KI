import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit v22", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
except Exception as e:
    st.error(f"Setup Fehler: {e}")
    st.stop()

# --- 2. MARKT-INDIKATOREN (VIX & FEAR & GREED) ---
def get_market_indicators():
    try:
        vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        spy = yf.Ticker("^GSPC").history(period="300d")
        cp = spy['Close'].iloc[-1]
        sma125 = spy['Close'].rolling(125).mean().iloc[-1]
        # Fear & Greed Näherung: Preis relativ zum 125-Tage-Schnitt
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
        
        # Korrektur-Statistik
        roll_max = h['High'].cummax()
        drawdown = (h['Low'] - roll_max) / roll_max
        avg_dd = round(drawdown.mean() * 100, 2)

        # RSI & MACD (Einfach)
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]
        
        ema12 = h['Close'].ewm(span=12, adjust=False).mean()
        ema26 = h['Close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "Korr_Akt": round(((cp / ath) - 1) * 100, 1),
            "Korr_Avg": avg_dd,
            "RSI": round(rsi, 1),
            "MACD_Signal": "Bullisch 🟢" if macd.iloc[-1] > macd.iloc[-2] else "Bärisch 🔴",
            "Trend": "Aufwärts 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Abwärts 📉",
            "Vol_Shock": "Ja ⚠️" if h['Volume'].iloc[-1] > h['Volume'].tail(20).mean() * 1.5 else "Nein"
        }
    except: return None

# --- 3. HEADER (MARKT-SITUATION) ---
vix, fg = get_market_indicators()
st.title("🏛️ Professional Investment Cockpit")

c1, c2 = st.columns(2)
c1.metric("VIX (Angst)", vix, delta="Hoch" if vix > 22 else "Normal", delta_color="inverse")
c2.metric("Fear & Greed Index", f"{fg}/100", delta="Gier" if fg > 55 else "Angst")

st.divider()

# --- 4. DATEN LADEN ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    m_data = []
    with st.spinner("Synchronisiere Markt- und Strategiedaten..."):
        for _, r in df_db.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                # Manueller Fair Value aus Datenbank
                fv = float(r.get('fair_value', 0))
                
                # Tranchen-Berechnung vom ATH
                t1 = m['ATH'] * 0.90
                t2 = m['ATH'] * 0.80
                
                # Strategie-Rating
                score = 0
                if m['RSI'] < 35: score += 1
                if m['Korr_Akt'] < m['Korr_Avg']: score += 1
                if m['Preis'] <= fv and fv > 0: score += 1
                
                if score >= 2: rating = "KAUFEN 🟢"
                elif score == 1: rating = "BEOBACHTEN 🟡"
                else: rating = "WARTEN ⚪"

                m_data.append({
                    "Ticker": r['ticker'], "Name": m['Name'], "Sektor": m['Sektor'],
                    "Kurs": m['Preis'], "FV": fv, 
                    "Korr %": m['Korr_Akt'], "Ø Korr %": m['Korr_Avg'],
                    "RSI": m['RSI'], "Trend": m['Trend'], "MACD": m['MACD_Signal'], "Vol": m['Vol_Shock'],
                    "T1 (-10%)": round(t1, 2), "T2 (-20%)": round(t2, 2),
                    "Empfehlung": rating
                })

    if m_data:
        df = pd.DataFrame(m_data)
        tab1, tab2, tab3 = st.tabs(["📊 Marktsituation", "🎯 Technische Indikatoren", "🚀 Strategie & Tranchen"])
        
        with tab1:
            st.subheader("Aktuelle Kurs- & Sektorübersicht")
            st.dataframe(df[["Ticker", "Name", "Sektor", "Kurs", "FV"]], use_container_width=True, hide_index=True)

        with tab2:
            st.subheader("Erweiterte technische Analyse")
            st.dataframe(df[["Ticker", "Korr %", "Ø Korr %", "RSI", "MACD", "Trend", "Vol"]], use_container_width=True, hide_index=True)

        with tab3:
            st.subheader("Einstiegs-Logik & Kauf-Tranchen")
            # Kombinierte Ansicht für schnelle Entscheidung
            st.dataframe(df[["Ticker", "Kurs", "FV", "T1 (-10%)", "T2 (-20%)", "Empfehlung"]].style.apply(
                lambda x: ['background-color: #004d00' if "🟢" in str(x.Empfehlung) else '' for i in x], axis=1),
                use_container_width=True, hide_index=True)
            
            st.info("💡 **Strategie:** KAUFEN (🟢) wird angezeigt, wenn mindestens 2 Kriterien erfüllt sind: RSI < 35, Kurs < Fair Value oder Korrektur > historischer Durchschnitt.")

# Sidebar Refresh
with st.sidebar:
    if st.button("🔄 Alle Daten aktualisieren"):
        st.cache_data.clear()
        st.rerun()
