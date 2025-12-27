import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit v9", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Initialisierungsfehler: {e}")
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

# --- 3. DATEN LADEN ---
try:
    res = supabase.table("watchlist").select("*").execute()
    df_db = pd.DataFrame(res.data)
except Exception as e:
    st.error(f"Fehler beim Laden der Supabase-Daten: {e}")
    df_db = pd.DataFrame()

# --- 4. SIDEBAR MANAGEMENT ---
with st.sidebar:
    st.header("⚙️ Verwaltung")
    
    view_option = st.selectbox("Watchlist Filter:", ["Alle", "Tranche", "Sparplan"])
    
    st.divider()
    st.subheader("➕ Aktie hinzufügen")
    with st.form("add_form", clear_on_submit=True):
        in_ticker = st.text_input("Ticker Symbol (z.B. AAPL)").upper()
        in_fv = st.number_input("Fair Value", min_value=0.0)
        in_type = st.selectbox("Zuweisung", ["Tranche", "Sparplan"])
        submit_add = st.form_submit_button("In Datenbank speichern")
        
        if submit_add and in_ticker:
            try:
                # FIX: Variable 'data' korrekt definiert
                new_entry = {
                    "ticker": in_ticker, 
                    "fair_value": in_fv, 
                    "watchlist_type": in_type
                }
                supabase.table("watchlist").insert(new_entry).execute()
                st.success(f"Erfolg: {in_ticker} hinzugefügt!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Datenbankfehler: {e}")

    st.divider()
    st.subheader("🗑️ Aktie löschen")
    if not df_db.empty and 'ticker' in df_db.columns:
        ticker_to_del = st.selectbox("Ticker wählen", ["-"] + df_db['ticker'].tolist())
        if st.button("Jetzt löschen") and ticker_to_del != "-":
            try:
                supabase.table("watchlist").delete().eq("ticker", ticker_to_del).execute()
                st.warning(f"{ticker_to_del} wurde gelöscht.")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Fehler beim Löschen: {e}")

    st.divider()
    base_mos = st.slider("Margin of Safety %", 0, 50, 15)
    t1_drop = st.slider("Tranche 1 (ATH-Korr %)", 5, 50, 15)

# --- 5. DASHBOARD ANZEIGE ---
vix, fg, spy_p = get_market_indicators()
st.title("🏛️ Professional Investment Cockpit")

# Banner
c1, c2, c3 = st.columns(3)
c1.metric("VIX Index", vix, "Angst-Barometer")
c2.metric("Fear & Greed", f"{fg}/100", "Marktstimmung")
c3.metric("S&P 500 (1Y)", f"{round(spy_p, 1)}%", "Benchmark")

if not df_db.empty:
    # SPALTEN-VALIDIERUNG
    if 'watchlist_type' not in df_db.columns:
        st.error("🚨 Spalte 'watchlist_type' fehlt in Supabase. Bitte manuell anlegen!")
        st.stop()

    # FILTERUNG
    if view_option != "Alle":
        df_show = df_db[df_db['watchlist_type'].str.lower() == view_option.lower()]
    else:
        df_show = df_db

    if df_show.empty:
        st.info(f"Keine Einträge für '{view_option}' vorhanden.")
    else:
        m_list, s_list, p_agg = [], [], []
        
        with st.spinner("Aktualisiere Kurse..."):
            for _, r in df_show.iterrows():
                m = get_metrics(r['ticker'])
                if m:
                    adj_fv = r['fair_value'] * (1 - (base_mos/100))
                    t1_p = m['ATH'] * (1 - t1_drop/100)
                    status = "🎯 BEREIT" if m['Preis'] <= t1_p and m['Preis'] <= adj_fv else "⏳ Warten"
                    
                    m_list.append({"Ticker": r['ticker'], "Name": m['Name'], "Kurs": m['Preis'], "Trend": m['Trend'], "RSI": m['RSI'], "Vol": m['Vol']})
                    s_list.append({"Ticker": r['ticker'], "Fair Value": r['fair_value'], "MoS-Preis": round(adj_fv, 2), "Abstand T1 %": round(((m['Preis']/t1_p)-1)*100, 1), "Status": status})
                    p_agg.append(m['Perf'])

        # Performance Check
        with st.expander("📈 DURCHSCHNITTS-PERFORMANCE DER LISTE"):
            if p_agg:
                pa = pd.DataFrame(p_agg).mean()
                pc = st.columns(5)
                for i, label in enumerate(["1M", "3M", "6M", "1Y", "2Y"]):
                    pc[i].metric(label, f"{round(pa[label], 2)}%")

        # Tabellen
        t1, t2 = st.tabs(["📊 Marktdaten", "🎯 Kauf-Strategie"])
        with t1: st.dataframe(pd.DataFrame(m_list), use_container_width=True, hide_index=True)
        with t2:
            st.dataframe(pd.DataFrame(s_list).style.apply(lambda x: ['background-color: #004d00' if "🎯" in str(x.Status) else '' for i in x], axis=1), use_container_width=True, hide_index=True)
else:
    st.info("Datenbank ist noch leer. Füge deine erste Aktie in der Sidebar hinzu!")
