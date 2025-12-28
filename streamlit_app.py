import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
from urllib.parse import quote

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit v26", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"Datenbank-Verbindungsfehler: {e}")
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
        
        # Korrektur-Statistik
        roll_max = h['High'].cummax()
        avg_dd = round(((h['Low'] - roll_max) / roll_max).mean() * 100, 2)

        # RSI
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]
        
        # Volumen Analyse
        avg_vol = h['Volume'].tail(20).mean()
        curr_vol = h['Volume'].iloc[-1]
        vol_info = "Normal"
        if curr_vol > avg_vol * 1.5:
            vol_info = "⚠️ LONG-Druck" if (cp - h['Close'].iloc[-2]) > 0 else "⚠️ SHORT-Druck"

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
st.title("🏛️ Professional Investment Cockpit")
c1, c2 = st.columns(2)
c1.metric("VIX (Angst)", vix)
c2.metric("Fear & Greed Index", f"{fg}/100")
st.divider()

# --- 4. DATEN LADEN ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    m_data = []
    with st.spinner("Marktdaten werden geladen..."):
        for _, r in df_db.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                fv = float(r.get('fair_value', 0))
                # Tranchen Fixierung vom ATH
                t1, t2 = m['ATH'] * 0.90, m['ATH'] * 0.80
                
                # Scoring für Empfehlung (Ohne KI, rein mathematisch)
                score = (1 if m['RSI'] < 35 else 0) + (1 if m['Korr_Akt'] < m['Korr_Avg'] else 0) + (1 if fv > 0 and m['Preis'] <= fv else 0)
                rating = "KAUFEN 🟢" if score >= 2 else "BEOBACHTEN 🟡" if score == 1 else "WARTEN ⚪"

                m_data.append({**m, "Ticker": r['ticker'], "FV": fv, "T1": round(t1, 2), "T2": round(t2, 2), "Empfehlung": rating})

    if m_data:
        df = pd.DataFrame(m_data)
        tab1, tab2, tab3 = st.tabs(["📊 Markt", "🎯 Technik", "🚀 Strategie"])
        
        with tab1: st.dataframe(df[["Ticker", "Name", "Sektor", "Preis", "FV"]], use_container_width=True, hide_index=True)
        with tab2: st.dataframe(df[["Ticker", "Korr_Akt", "Korr_Avg", "RSI", "Trend", "Vol_Info"]], use_container_width=True, hide_index=True)
        with tab3: st.dataframe(df[["Ticker", "Preis", "FV", "T1", "T2", "Empfehlung"]].style.apply(lambda x: ['background-color: #004d00' if "🟢" in str(x.Empfehlung) else '' for i in x], axis=1), use_container_width=True, hide_index=True)

        # --- 5. PERPLEXITY DEEP-DIVE LINK ---
        st.divider()
        st.subheader("🔍 Externer Deep-Dive (Perplexity Pro)")
        sel = st.selectbox("Aktie für Analyse wählen:", df['Ticker'].tolist())
        d = next(item for item in m_data if item["Ticker"] == sel)
        
        # Erstellung des Prompts für die URL
        perplexity_prompt = f"""Bewerte die Aktie {sel} ({d['Name']}) kurzzusammengefasst:
1. Wichtige News der letzten 10 Tage.
2. Derzeitige Marktsituation (Branche & Makro).
3. Technische Analyse (RSI ist {d['RSI']}, Korrektur {d['Korr_Akt']}%).
4. Aktuelle Prognosen & Kursziele.
5. Einstiegsbewertung (Grund & Empfehlung).
Daten: Kurs {d['Preis']}, Fair Value {d['FV']}."""

        encoded_prompt = quote(perplexity_prompt)
        url = f"https://www.perplexity.ai/?q={encoded_prompt}"
        
        st.link_button(f"🚀 {sel} Analyse auf Perplexity öffnen", url)

with st.sidebar:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
