import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit ", layout="wide")

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
        
        # Korrektur-Statistik
        roll_max = h['High'].cummax()
        avg_dd = round(((h['Low'] - roll_max) / roll_max).mean() * 100, 2)

        # RSI & MACD
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]
        
        # Volumen Analyse (Long/Short Hinweis)
        avg_vol = h['Volume'].tail(20).mean()
        curr_vol = h['Volume'].iloc[-1]
        price_change = h['Close'].iloc[-1] - h['Close'].iloc[-2]
        
        vol_info = "Normal"
        if curr_vol > avg_vol * 1.5:
            vol_info = "⚠️ LONG-Druck" if price_change > 0 else "⚠️ SHORT-Druck"

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "Korr_Akt": round(((cp / ath) - 1) * 100, 1),
            "Korr_Avg": avg_dd,
            "RSI": round(rsi, 1),
            "Trend": "Aufwärts 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Abwärts 📉",
            "Vol_Info": vol_info
        }
    except: return None

# --- 3. HEADER ---
vix, fg = get_market_indicators()
st.title("🏛️ Investment Cockpit")
c1, c2 = st.columns(2)
c1.metric("VIX (Angst)", vix)
c2.metric("Fear & Greed Index", f"{fg}/100")
st.divider()

# --- 4. DATEN LADEN ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    m_data = []
    with st.spinner("Analysiere Daten..."):
        for _, r in df_db.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                fv = float(r.get('fair_value', 0))
                t1, t2 = m['ATH'] * 0.90, m['ATH'] * 0.80
                
                # Scoring für Empfehlung
                score = 0
                if m['RSI'] < 35: score += 1
                if m['Korr_Akt'] < m['Korr_Avg']: score += 1
                if m['Preis'] <= fv and fv > 0: score += 1
                rating = "KAUFEN 🟢" if score >= 2 else "BEOBACHTEN 🟡" if score == 1 else "WARTEN ⚪"

                m_data.append({
                    **m, "Ticker": r['ticker'], "FV": fv, 
                    "T1 (-10%)": round(t1, 2), "T2 (-20%)": round(t2, 2),
                    "Empfehlung": rating
                })

    if m_data:
        df = pd.DataFrame(m_data)
        tab1, tab2, tab3 = st.tabs(["📊 Markt", "🎯 Technik", "🚀 Strategie"])
        
        with tab1: st.dataframe(df[["Ticker", "Name", "Sektor", "Preis", "FV", "RSI"]], use_container_width=True, hide_index=True)
        with tab2: st.dataframe(df[["Ticker", "Korr_Akt", "Korr_Avg", "RSI", "Trend", "Vol_Info"]], use_container_width=True, hide_index=True)
        with tab3: st.dataframe(df[["Ticker", "Preis", "FV", "T1 (-10%)", "T2 (-20%)", "RSI", "Empfehlung"]].style.apply(
                lambda x: ['background-color: #004d00' if "🟢" in str(x.Empfehlung) else '' for i in x], axis=1), 
                use_container_width=True, hide_index=True)

        # --- 5. KI ANALYSE BUTTON (DEIN PROMPT) ---
        st.divider()
        st.subheader("🤖 KI Deep-Dive Analyse")
        sel_ticker = st.selectbox("Wähle eine Aktie für die Detail-Bewertung:", df['Ticker'].tolist())
        
        if st.button("Deep-Dive Analyse starten"):
            d = next(item for item in m_data if item["Ticker"] == sel_ticker)
            prompt = f"""
            Bewerte die Aktie {sel_ticker} ({d['Name']}) kurzzusammengefasst mit folgenden Punkten:
            1. Wichtige News der letzten 10 Tage: Fasse die relevantesten Nachrichten zusammen.
            2. Derzeitige Marktsituation: Beschreibe kurz das Umfeld (Branche, Makro).
            3. Technische Analyse: Analysiere den RSI von {d['RSI']}, erkläre ob überkauft/überverkauft und Folgen.
            4. Aktuelle Prognosen: Überblick über Analystenschätzungen/Kursziele (sofern bekannt).
            5. Einstiegsbewertung: Beurteile ob Einstieg sinnvoll, abwarten oder kein Einstieg mit knapper Begründung.
            Nutze die Daten: Kurs {d['Preis']}, Fair Value {d['FV']}, Korrektur {d['Korr_Akt']}%.
            """
            with st.chat_message("assistant"):
                with st.spinner("KI durchsucht aktuelle Marktdaten..."):
                    st.markdown(ki_model.generate_content(prompt).text)

with st.sidebar:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
