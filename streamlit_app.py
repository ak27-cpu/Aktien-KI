import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
from urllib.parse import quote

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit v27 - FINAL", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"Datenbank-Fehler: {e}")
    st.stop()

# --- 2. MARKT-INDIKATOREN (VIX & FEAR & GREED) ---
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
        sma200 = h['Close'].rolling(200).mean().iloc[-1]
        
        # Korrektur-Statistik
        roll_max = h['High'].cummax()
        avg_dd = round(((h['Low'] - roll_max) / roll_max).mean() * 100, 2)

        # RSI
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]
        
        # Volumen & Trendstärke
        vol_change = (h['Volume'].iloc[-1] / h['Volume'].tail(20).mean())
        trend_dist = round(((cp / sma200) - 1) * 100, 1)
        
        vol_info = "Normal"
        if vol_change > 1.5:
            vol_info = "⚠️ LONG-Druck" if (cp - h['Close'].iloc[-2]) > 0 else "⚠️ SHORT-Druck"

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "Korr_Akt": round(((cp / ath) - 1) * 100, 1),
            "Korr_Avg": avg_dd,
            "RSI": round(rsi, 1),
            "Trend": "Bull 📈" if cp > sma200 else "Bear 📉",
            "Trend_Stärke": f"{trend_dist}% vs GD200",
            "Vol_Info": vol_info
        }
    except: return None

# --- 3. HEADER ---
vix, fg = get_market_indicators()
st.title("🏛️ Professional Investment Cockpit")
c1, c2 = st.columns(2)
c1.metric("VIX (Angst)", vix, delta="Vola" if vix > 22 else "Ruhig", delta_color="inverse")
c2.metric("Fear & Greed Index", f"{fg}/100", delta="Gier" if fg > 55 else "Angst")
st.divider()

# --- 4. DATEN LADEN ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    m_data = []
    with st.spinner("Aktualisiere Marktpreise..."):
        for _, r in df_db.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                fv = float(r.get('fair_value', 0))
                t1, t2 = m['ATH'] * 0.90, m['ATH'] * 0.80
                
                # Strategie Score
                score = (1 if m['RSI'] < 35 else 0) + (1 if m['Korr_Akt'] < m['Korr_Avg'] else 0) + (1 if fv > 0 and m['Preis'] <= fv else 0)
                rating = "KAUFEN 🟢" if score >= 2 else "BEOBACHTEN 🟡" if score == 1 else "WARTEN ⚪"

                m_data.append({**m, "Ticker": r['ticker'], "FV": fv, "T1": round(t1, 2), "T2": round(t2, 2), "Empfehlung": rating})

    if m_data:
        df = pd.DataFrame(m_data)
        tab1, tab2, tab3 = st.tabs(["📊 Marktsituation", "🎯 Technische Indikatoren", "🚀 Strategie & Tranchen"])
        
        with tab1:
            st.dataframe(df[["Ticker", "Name", "Sektor", "Preis", "FV"]], use_container_width=True, hide_index=True)

        with tab2:
            st.dataframe(df[["Ticker", "Korr_Akt", "Korr_Avg", "RSI", "Trend", "Trend_Stärke", "Vol_Info"]], use_container_width=True, hide_index=True)

        with tab3:
            st.dataframe(df[["Ticker", "Preis", "FV", "T1", "T2", "Empfehlung"]].style.apply(
                lambda x: ['background-color: #004d00' if "🟢" in str(x.Empfehlung) else '' for i in x], axis=1), 
                use_container_width=True, hide_index=True)

        # --- 5. PERPLEXITY PRO DEEP-DIVE ---
        st.divider()
        st.subheader("🔍 KI Research (Perplexity Pro)")
        sel = st.selectbox("Aktie für Deep-Dive wählen:", df['Ticker'].tolist())
        d = next(item for item in m_data if item["Ticker"] == sel)
        
        perp_prompt = f"""Analysiere die Aktie {sel} ({d['Name']}) tiefgreifend für meine Investmentstrategie:
1. News-Check: Was waren die kritischsten Ereignisse der letzten 10 Tage? (Fokus auf Earnings, Upgrades/Downgrades).
2. Sektor-Kontext: Wie steht die Branche aktuell da? (Makro-Einflüsse).
3. Technische Einordnung: Der RSI liegt bei {d['RSI']}, die Korrektur vom Hoch bei {d['Korr_Akt']}%. Ist das historisch eine Kaufgelegenheit?
4. Analysten-Target: Wie hoch ist das durchschnittliche Kursziel und der Konsens (Buy/Hold/Sell)?
5. Strategie-Abgleich: Mein Fair Value liegt bei {d['FV']}. Meine Einstiegs-Tranchen liegen bei {d['T1']} (-10%) und {d['T2']} (-20%).
Basierend auf dem aktuellen Kurs von {d['Preis']} – was ist deine fundierte Empfehlung?"""

        url = f"https://www.perplexity.ai/?q={quote(perp_prompt)}"
        st.link_button(f"🚀 {sel} Deep-Dive auf Perplexity Pro starten", url, use_container_width=True)

with st.sidebar:
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()
