import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit Ultimate v10", layout="wide")

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
        spy = yf.Ticker("^GSPC").history(period="300d")
        cp = spy['Close'].iloc[-1]
        sma125 = spy['Close'].rolling(125).mean().iloc[-1]
        fg_score = int((cp / sma125) * 50)
        return round(vix, 2), min(100, fg_score), ((cp / spy['Close'].iloc[-252]) - 1) * 100
    except: return 20.0, 50, 0.0

@st.cache_data(ttl=1800)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        # 3 Jahre Daten laden für stabile Performance-Vergleiche
        h = s.history(period="3y")
        if h.empty: return None
        info = s.info
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        
        # PRÄZISE PERFORMANCE LOGIK
        def get_exact_perf(days):
            target_date = h.index[-1] - timedelta(days=days)
            # Findet den nächsten verfügbaren Handelstag zum Zieldatum
            idx = h.index.get_indexer([target_date], method='nearest')[0]
            old_price = h['Close'].iloc[idx]
            return round(((cp / old_price) - 1) * 100, 2)

        # Jährliche Performance (p.a.) für 2 Jahre berechnen
        perf_2y_total = get_exact_perf(730)
        perf_2y_pa = round(((1 + perf_2y_total/100)**(1/2) - 1) * 100, 2)

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "RSI": round((lambda d: 100 - (100 / (1 + (d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))).iloc[-1])(h['Close'].diff()), 1),
            "Trend": "Bull 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Bear 📉",
            "Vol": round(h['Volume'].iloc[-1] / h['Volume'].tail(20).mean(), 2),
            "KGV": info.get('trailingPE', 0),
            "Div": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0,
            "Perf": {
                "1M": get_exact_perf(30),
                "3M": get_exact_perf(91),
                "6M": get_exact_perf(182),
                "1Y": get_exact_perf(365),
                "2Y p.a.": perf_2y_pa
            }
        }
    except: return None

# --- 3. DATEN LADEN & SIDEBAR ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

with st.sidebar:
    st.header("⚙️ Steuerung")
    view_option = st.selectbox("Watchlist Filter:", ["Alle", "Tranche", "Sparplan"])
    
    st.divider()
    with st.expander("➕ Aktie hinzufügen"):
        with st.form("add_form", clear_on_submit=True):
            in_ticker = st.text_input("Ticker").upper()
            in_fv = st.number_input("Fair Value", min_value=0.0)
            in_type = st.selectbox("Typ", ["Tranche", "Sparplan"])
            if st.form_submit_button("Speichern"):
                supabase.table("watchlist").insert({"ticker": in_ticker, "fair_value": in_fv, "watchlist_type": in_type}).execute()
                st.cache_data.clear()
                st.rerun()

    if not df_db.empty:
        with st.expander("🗑️ Aktie löschen"):
            ticker_del = st.selectbox("Ticker", ["-"] + df_db['ticker'].tolist())
            if st.button("Löschen") and ticker_del != "-":
                supabase.table("watchlist").delete().eq("ticker", ticker_del).execute()
                st.cache_data.clear()
                st.rerun()

    st.divider()
    base_mos = st.slider("Margin of Safety %", 0, 50, 15)
    t1_drop = st.slider("Tranche 1 (ATH-Korr %)", 5, 50, 15)

# --- 4. DASHBOARD ---
vix, fg, spy_p = get_market_indicators()
st.title("🏛️ Professional Investment Cockpit")

c1, c2, c3 = st.columns(3)
c1.metric("VIX Index", vix, "Volatilität")
c2.metric("Fear & Greed", f"{fg}/100", "Sentiment")
c3.metric("S&P 500 (1Y)", f"{round(spy_p, 1)}%", "Benchmark")

if not df_db.empty:
    if view_option != "Alle":
        df_show = df_db[df_db['watchlist_type'].str.lower() == view_option.lower()]
    else:
        df_show = df_db

    if not df_show.empty:
        m_list, s_list, p_agg = [], [], []
        for _, r in df_show.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                adj_fv = r['fair_value'] * (1 - (base_mos/100))
                t1_p = m['ATH'] * (1 - t1_drop/100)
                status = "🎯 BEREIT" if m['Preis'] <= t1_p and m['Preis'] <= adj_fv else "⏳ Warten"
                
                m_list.append({"Ticker": r['ticker'], "Name": m['Name'], "Kurs": m['Preis'], "Trend": m['Trend'], "RSI": m['RSI'], "Vol": m['Vol'], "KGV": m['KGV']})
                s_list.append({"Ticker": r['ticker'], "Fair Value": r['fair_value'], "MoS-Preis": round(adj_fv, 2), "Abstand T1 %": round(((m['Preis']/t1_p)-1)*100, 1), "Status": status, "Div %": m['Div']})
                p_agg.append(m['Perf'])

        # Performance Check
        with st.expander("📈 PRÄZISE PERFORMANCE-ANALYSE (DURCHSCHNITT)"):
            pa = pd.DataFrame(p_agg).mean()
            cols = st.columns(5)
            for i, (k, v) in enumerate(pa.items()):
                cols[i].metric(k, f"{round(v, 2)}%")

        # Tabellen
        t1, t2 = st.tabs(["📊 Marktdaten", "🎯 Kauf-Strategie"])
        with t1: st.dataframe(pd.DataFrame(m_list), use_container_width=True, hide_index=True)
        with t2: st.dataframe(pd.DataFrame(s_list).style.apply(lambda x: ['background-color: #004d00' if "🎯" in str(x.Status) else '' for i in x], axis=1), use_container_width=True, hide_index=True)

        # --- 5. KI ANALYSE TERMINAL ---
        st.divider()
        st.subheader("🤖 KI Analyse Terminal")
        ki_ticker = st.selectbox("Aktie wählen:", [x['Ticker'] for x in m_list])
        ki_task = st.selectbox("Analyse-Modus:", [
            "1. Full Equity Report (Fundamentaldaten & Moat)",
            "2. Fair Value Check (DCF & KGV Vergleich)",
            "3. Dividenden-Sicherheit & Historie",
            "4. Crash-Resistenz & Risiko-Profil"
        ])
        
        if st.button("KI-Prozess starten"):
            m_ctx = next(i for i in m_list if i["Ticker"] == ki_ticker)
            s_ctx = next(i for i in s_list if i["Ticker"] == ki_ticker)
            prompt = f"""Führe Analyse '{ki_task}' für {ki_ticker} ({m_ctx['Name']}) durch.
            Daten: Kurs {m_ctx['Kurs']}, KGV {m_ctx['KGV']}, RSI {m_ctx['RSI']}, Div {s_ctx['Div %']}%.
            Status: {s_ctx['Status']}. Marktumfeld: VIX {vix}, F&G {fg}.
            Antworte präzise wie ein Investmentbanker."""
            with st.chat_message("assistant"):
                st.markdown(ki_model.generate_content(prompt).text)

else:
    st.info("Keine Daten vorhanden.")
