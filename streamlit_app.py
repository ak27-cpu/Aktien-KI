import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit v7", layout="wide")

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
        spy = yf.Ticker("^GSPC").history(period="252d")
        cp = spy['Close'].iloc[-1]
        sma125 = spy['Close'].rolling(125).mean().iloc[-1]
        fg_score = int((cp / sma125) * 50)
        return round(vix, 2), min(100, fg_score), ((cp / spy['Close'].iloc[0]) - 1) * 100
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
        
        def perf(d): return round(((cp / h['Close'].iloc[-d]) - 1) * 100, 2) if len(h) >= d else 0.0

        return {
            "Name": info.get('longName', ticker),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "RSI": round((lambda d: 100 - (100 / (1 + (d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))).iloc[-1])(h['Close'].diff()), 1),
            "Trend": "Bull 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Bear 📉",
            "Vol": round(h['Volume'].iloc[-1] / h['Volume'].tail(20).mean(), 2),
            "Perf": {"1M": perf(21), "3M": perf(63), "6M": perf(126), "1Y": perf(252), "2Y": perf(504)}
        }
    except: return None

# --- 3. SIDEBAR: FILTER & MANAGEMENT ---
with st.sidebar:
    st.header("⚙️ Cockpit Kontrolle")
    view = st.radio("Ansicht wählen:", ["Alle Aktien", "Tranchen-Käufe", "Sparpläne"])
    
    st.divider()
    st.subheader("➕ Aktie hinzufügen")
    new_ticker = st.text_input("Ticker (z.B. AAPL)").upper()
    new_fv = st.number_input("Manueller Fair Value", min_value=0.0, step=1.0)
    new_type = st.selectbox("Typ", ["Tranche", "Sparplan"])
    
    if st.button("Hinzufügen"):
        if new_ticker:
            data = {"ticker": new_ticker, "fair_value": new_fv, "watchlist_type": new_type}
            supabase.table("watchlist").insert(data).execute()
            st.success(f"{new_ticker} gespeichert!")
            st.rerun()

    st.divider()
    st.subheader("🗑️ Aktie löschen")
    # Ticker Liste für Dropdown laden
    ticker_res = supabase.table("watchlist").select("ticker").execute()
    existing_tickers = [item['ticker'] for item in ticker_res.data]
    del_ticker = st.selectbox("Ticker wählen", ["-"] + existing_tickers)
    
    if st.button("Löschen") and del_ticker != "-":
        supabase.table("watchlist").delete().eq("ticker", del_ticker).execute()
        st.warning(f"{del_ticker} entfernt.")
        st.rerun()

    st.divider()
    base_mos = st.slider("Margin of Safety %", 0, 50, 15)
    t1_drop = st.slider("Tranche 1 (ATH-Korr %)", 5, 50, 15)
    if st.button("🔄 Global Refresh"):
        st.cache_data.clear()
        st.rerun()

# --- 4. DASHBOARD ANZEIGE ---
vix, fg, spy_p = get_market_indicators()
st.title("🏛️ Ultimate Terminal v7")

c1, c2, c3 = st.columns(3)
c1.metric("VIX Index", vix)
c2.metric("Fear & Greed", f"{fg}/100")
c3.metric("S&P 500 (1Y)", f"{round(spy_p, 1)}%")

# Daten aus Supabase laden
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    # Filter
    if view == "Tranchen-Käufe":
        df_show = df_db[df_db['watchlist_type'] == 'Tranche']
    elif view == "Sparpläne":
        df_show = df_db[df_db['watchlist_type'] == 'Sparplan']
    else:
        df_show = df_db

    m_list, s_list, p_agg = [], [], []
    
    with st.spinner("Synchronisiere Daten..."):
        for _, r in df_show.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                adj_fv = r['fair_value'] * (1 - (base_mos/100))
                t1_p = m['ATH'] * (1 - t1_drop/100)
                status = "🎯 BEREIT" if m['Preis'] <= t1_p and m['Preis'] <= adj_fv else "⏳ Warten"
                
                m_list.append({"Ticker": r['ticker'], "Name": m['Name'], "Kurs": m['Preis'], "Trend": m['Trend'], "RSI": m['RSI'], "Vol": m['Vol']})
                s_list.append({"Ticker": r['ticker'], "Fair Value": r['fair_value'], "MoS-Preis": round(adj_fv, 2), "Abstand T1 %": round(((m['Preis']/t1_p)-1)*100, 1), "Status": status})
                p_agg.append(m['Perf'])

    # Performance Expander
    with st.expander("📈 PERFORMANCE ÜBERSICHT"):
        if p_agg:
            pa = pd.DataFrame(p_agg).mean()
            pc = st.columns(5)
            for i, label in enumerate(["1M", "3M", "6M", "1Y", "2Y"]):
                pc[i].metric(label, f"{round(pa[label], 2)}%")

    # Tabellen
    t1, t2 = st.tabs(["📊 Markt", "🎯 Strategie"])
    with t1: st.dataframe(pd.DataFrame(m_list), use_container_width=True, hide_index=True)
    with t2:
        df_s = pd.DataFrame(s_list)
        st.dataframe(df_s.style.apply(lambda x: ['background-color: #004d00' if "🎯" in str(x.Status) else '' for i in x], axis=1), use_container_width=True, hide_index=True)

else:
    st.info("Keine Aktien gefunden. Nutze die Sidebar zum Hinzufügen!")
