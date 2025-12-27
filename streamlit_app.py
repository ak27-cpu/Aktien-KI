import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. SETUP ---
st.set_page_config(page_title="Ultimate Cockpit v13", layout="wide")

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
        
        # Berechnung: Durchschnittlicher Drawdown (Korrektur) der letzten 2 Jahre
        # Wir messen die Tiefpunkte relativ zu den vorangegangenen Hochs
        roll_max = h['High'].cummax()
        drawdowns = (h['Low'] - roll_max) / roll_max
        avg_drawdown = round(drawdowns.mean() * 100, 2)

        def get_perf(d):
            try:
                idx = h.index.get_indexer([h.index[-1] - timedelta(days=d)], method='nearest')[0]
                return round(((cp / h['Close'].iloc[idx]) - 1) * 100, 2)
            except: return 0.0

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'Unbekannt'),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "ATH_Dist": round(((cp / ath) - 1) * 100, 1),
            "Avg_Korrektur": avg_drawdown,
            "RSI": round((lambda d: 100 - (100 / (1 + (d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))).iloc[-1])(h['Close'].diff()), 1),
            "Trend": "Bull 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Bear 📉",
            "Vol": round(h['Volume'].iloc[-1] / h['Volume'].tail(20).mean(), 2),
            "KGV": info.get('trailingPE', 0),
            "Div": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0,
            "Perf": {"1M": get_perf(30), "1Y": get_perf(365)}
        }
    except: return None

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("📂 Cockpit Filter")
    view = st.radio("Watchlist wählen:", ["Alle", "Tranche", "Sparplan"])
    st.divider()
    base_mos = st.slider("Margin of Safety % (T1)", 0, 50, 15)
    t2_drop = st.slider("ATH-Korrektur % (T2)", 10, 60, 30)
    
    with st.expander("➕ Aktie hinzufügen"):
        with st.form("add_form", clear_on_submit=True):
            in_ticker = st.text_input("Ticker").upper()
            in_fv = st.number_input("Fair Value", min_value=0.0)
            in_type = st.selectbox("Zuweisung", ["Tranche", "Sparplan"])
            if st.form_submit_button("Speichern"):
                supabase.table("watchlist").insert({"ticker": in_ticker, "fair_value": in_fv, "watchlist_type": in_type}).execute()
                st.cache_data.clear()
                st.rerun()

# --- 4. DASHBOARD ---
vix, fg, spy_p = get_market_indicators()
st.title(f"🏛️ Strategy Cockpit: {view}")

c1, c2, c3 = st.columns(3)
c1.metric("VIX", vix, "Angst-Level")
c2.metric("Fear & Greed", f"{fg}/100", "Stimmung")
c3.metric("S&P 500 (1Y)", f"{round(spy_p, 1)}%", "Benchmark")

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
            # Signal Logik
            is_t1 = m['Preis'] <= t1
            is_t2 = m['Preis'] <= t2
            status = "🎯 BEREIT" if (is_t1 or is_t2) else "⏳ Warten"
            
            m_data.append({
                "Ticker": r['ticker'], "Name": m['Name'], "Sektor": m['Sektor'], "Kurs": m['Preis'], 
                "Fair Value": r['fair_value'], "T1 (MoS)": round(t1, 2), "T2 (ATH)": round(t2, 2),
                "Akt. Korr %": m['ATH_Dist'], "Ø Korr %": m['Avg_Korrektur'],
                "RSI": m['RSI'], "Trend": m['Trend'], "KGV": m['KGV'], "Div %": m['Div'], 
                "Status": status, "1M %": m['Perf']['1M'], "1Y %": m['Perf']['1Y']
            })

    if m_data:
        df = pd.DataFrame(m_data)
        
        tab1, tab2, tab3 = st.tabs(["📊 Marktdaten", "🎯 Technischer Einstieg", "📉 Korrektur & Sektoren"])
        
        with tab1:
            st.subheader("Fundamentalanalyse & Performance")
            # Fokus auf Sektor, KGV, Dividende und Kursentwicklung
            st.dataframe(df[["Ticker", "Name", "Sektor", "Kurs", "KGV", "Div %", "1Y %"]], use_container_width=True, hide_index=True)
            
        with tab2:
            st.subheader("Strategische Kaufzonen")
            # Fokus auf Einstiegs-Preise
            st.dataframe(df[["Ticker", "Kurs", "Fair Value", "T1 (MoS)", "T2 (ATH)", "Status"]].style.apply(lambda x: ['background-color: #004d00' if "🎯" in str(x.Status) else '' for i in x], axis=1), use_container_width=True, hide_index=True)
            
        with tab3:
            st.subheader("Technische Korrektur-Analyse")
            # Fokus auf Drawdown-Vergleich und Momentum
            st.dataframe(df[["Ticker", "Sektor", "Akt. Korr %", "Ø Korr %", "RSI", "Trend"]].sort_values("Akt. Korr %"), use_container_width=True, hide_index=True)

        # KI Deep Dive
        st.divider()
        sel = st.selectbox("Deep Dive Analyse:", df['Ticker'])
        if st.button("KI Report erstellen"):
            r = df[df['Ticker'] == sel].iloc[0]
            prompt = f"Analyse {sel} ({r['Sektor']}). Aktuelle Korrektur {r['Akt. Korr %']}% vs historischer Ø {r['Ø Korr %']}%. RSI {r['RSI']}. Status {r['Status']}. Gib eine fundierte Meinung ab."
            with st.chat_message("assistant"):
                st.markdown(ki_model.generate_content(prompt).text)
else:
    st.info("Keine Daten. Nutze die Sidebar.")
