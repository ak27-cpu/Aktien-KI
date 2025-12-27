import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit v12", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Setup Fehler: {e}")
    st.stop()

# --- 2. DATEN-FUNKTIONEN ---
def get_market_indicators():
    try:
        vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        spy = yf.Ticker("^GSPC").history(period="300d")
        cp = spy['Close'].iloc[-1]
        sma125 = spy['Close'].rolling(125).mean().iloc[-1]
        return round(vix, 2), int((cp / sma125) * 50), ((cp / spy['Close'].iloc[-252]) - 1) * 100
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
        
        # Performance & RSI
        def get_perf(d):
            try:
                old = h['Close'].iloc[h.index.get_indexer([h.index[-1] - timedelta(days=d)], method='nearest')[0]]
                return round(((cp / old) - 1) * 100, 2)
            except: return 0.0

        rsi = (lambda d: 100 - (100 / (1 + (d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))).iloc[-1])(h['Close'].diff())

        return {
            "Name": info.get('longName', ticker),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "ATH_Dist": round(((cp / ath) - 1) * 100, 1),
            "RSI": round(rsi, 1),
            "Trend": "Bull 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Bear 📉",
            "Vol": round(h['Volume'].iloc[-1] / h['Volume'].tail(20).mean(), 2),
            "KGV": info.get('trailingPE', 0),
            "Div": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0,
            "Perf": {"1M": get_perf(30), "1Y": get_perf(365)}
        }
    except: return None

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("📂 Filter & Management")
    view = st.radio("Watchlist wählen:", ["Alle", "Tranche", "Sparplan"])
    st.divider()
    base_mos = st.slider("Margin of Safety %", 0, 50, 15)
    t2_drop = st.slider("Tranche 2 (ATH-Korr %)", 10, 60, 30)
    if st.button("🔄 Global Refresh"):
        st.cache_data.clear()
        st.rerun()

# --- 4. DASHBOARD ---
vix, fg, spy_p = get_market_indicators()
st.title(f"🏛️ Cockpit: {view}")

# Banner
c1, c2, c3 = st.columns(3)
c1.metric("VIX", vix)
c2.metric("Fear & Greed", f"{fg}/100")
c3.metric("S&P 500 (1Y)", f"{round(spy_p, 1)}%")

res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    if view != "Alle":
        df_show = df_db[df_db['watchlist_type'].str.lower() == view.lower()]
    else:
        df_show = df_db

    m_data = []
    for _, r in df_show.iterrows():
        m = get_metrics(r['ticker'])
        if m:
            t1 = r['fair_value'] * (1 - (base_mos/100))
            t2 = m['ATH'] * (1 - (t2_drop/100))
            status = "🎯 BEREIT" if m['Preis'] <= t1 or m['Preis'] <= t2 else "⏳ Warten"
            
            m_data.append({
                "Ticker": r['ticker'], "Name": m['Name'], "Kurs": m['Preis'], 
                "Fair Value": r['fair_value'], "T1 (MoS)": round(t1, 2), "T2 (ATH)": round(t2, 2),
                "ATH-Dist %": m['ATH_Dist'], "RSI": m['RSI'], "Trend": m['Trend'], 
                "Vol": m['Vol'], "KGV": m['KGV'], "Div %": m['Div'], "Status": status,
                "1M %": m['Perf']['1M'], "1Y %": m['Perf']['1Y']
            })

    if m_data:
        df = pd.DataFrame(m_data)
        
        # --- UNTERTEILUNG IN DIE 3 SEKTIONEN ---
        tab1, tab2, tab3 = st.tabs(["📊 Marktdaten", "🎯 Technischer Einstieg", "📉 Korrektur Phasen"])
        
        with tab1:
            st.subheader("Fundamentale & Marktdaten")
            st.dataframe(df[["Ticker", "Name", "Kurs", "KGV", "Div %", "1M %", "1Y %"]], use_container_width=True, hide_index=True)
            
        with tab2:
            st.subheader("Einstiegs-Logik (Kaufzonen)")
            st.dataframe(df[["Ticker", "Kurs", "Fair Value", "T1 (MoS)", "T2 (ATH)", "Status"]].style.apply(lambda x: ['background-color: #004d00' if "🎯" in str(x.Status) else '' for i in x], axis=1), use_container_width=True, hide_index=True)
            
        with tab3:
            st.subheader("Analyse der Korrektur & Dynamik")
            st.dataframe(df[["Ticker", "Name", "ATH-Dist %", "RSI", "Trend", "Vol"]].sort_values("ATH-Dist %"), use_container_width=True, hide_index=True)

        # KI Deep Dive
        st.divider()
        sel = st.selectbox("KI-Analyse für:", df['Ticker'])
        if st.button("Start AI Report"):
            r = df[df['Ticker'] == sel].iloc[0]
            prompt = f"Analysiere {sel}. Kurs {r['Kurs']}, RSI {r['RSI']}, Abstand zum ATH {r['ATH-Dist %']}%. Ist die Korrektur eine Kaufchance?"
            with st.chat_message("assistant"):
                st.markdown(ki_model.generate_content(prompt).text)
else:
    st.info("Keine Daten gefunden.")
