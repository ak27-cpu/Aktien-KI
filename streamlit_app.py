import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Cockpit v11", layout="wide")

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
        h = s.history(period="3y")
        if h.empty: return None
        info = s.info
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        
        def get_exact_perf(days):
            target_date = h.index[-1] - timedelta(days=days)
            idx = h.index.get_indexer([target_date], method='nearest')[0]
            old_price = h['Close'].iloc[idx]
            return round(((cp / old_price) - 1) * 100, 2)

        perf_2y_total = get_exact_perf(730)
        perf_2y_pa = round(((1 + perf_2y_total/100)**(1/2) - 1) * 100, 2)

        return {
            "Name": info.get('longName', ticker),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "ATH_Dist": round(((cp / ath) - 1) * 100, 1),
            "RSI": round((lambda d: 100 - (100 / (1 + (d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))).iloc[-1])(h['Close'].diff()), 1),
            "Trend": "Bull 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Bear 📉",
            "Vol": round(h['Volume'].iloc[-1] / h['Volume'].tail(20).mean(), 2),
            "KGV": info.get('trailingPE', 0),
            "Div": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0,
            "Avg_Perf": round((get_exact_perf(30) + get_exact_perf(91) + get_exact_perf(182) + get_exact_perf(365)) / 4, 2),
            "Perf": {"1M": get_exact_perf(30), "1Y": get_exact_perf(365), "2Y p.a.": perf_2y_pa}
        }
    except: return None

# --- 3. DATEN LADEN & SIDEBAR ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

with st.sidebar:
    st.header("⚙️ Verwaltung")
    view_option = st.selectbox("Hauptansicht:", ["Tranchen-Käufe", "Sparpläne", "ATH-Korrektur Check (Alle)"])
    
    st.divider()
    base_mos = st.slider("Margin of Safety %", 0, 50, 15)
    t2_drop = st.slider("Tranche 2 (Korrektur vom ATH %)", 10, 60, 30)
    
    with st.expander("➕ Aktie hinzufügen"):
        with st.form("add_form", clear_on_submit=True):
            in_ticker = st.text_input("Ticker").upper()
            in_fv = st.number_input("Fair Value", min_value=0.0)
            in_type = st.selectbox("Typ", ["Tranche", "Sparplan"])
            if st.form_submit_button("Speichern"):
                supabase.table("watchlist").insert({"ticker": in_ticker, "fair_value": in_fv, "watchlist_type": in_type}).execute()
                st.cache_data.clear()
                st.rerun()

    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

# --- 4. DASHBOARD ---
vix, fg, spy_p = get_market_indicators()
st.title("🏛️ Professional Multi-Strategy Cockpit")

# Marktlage-Banner
c1, c2, c3 = st.columns(3)
c1.metric("VIX", vix, "Angst")
c2.metric("Fear & Greed", f"{fg}/100", "Stimmung")
c3.metric("S&P 500 (1Y)", f"{round(spy_p, 1)}%", "Benchmark")

if not df_db.empty:
    # Filter-Logik für die 3 Listen
    if "ATH-Korrektur" in view_option:
        df_show = df_db
    elif "Sparpläne" in view_option:
        df_show = df_db[df_db['watchlist_type'].str.lower() == "sparplan"]
    else:
        df_show = df_db[df_db['watchlist_type'].str.lower() == "tranche"]

    m_data = []
    with st.spinner("Analysiere Daten..."):
        for _, r in df_show.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                # Berechnungen für Tranche 1 & 2
                t1_price = r['fair_value'] * (1 - (base_mos/100))
                t2_price = m['ATH'] * (1 - (t2_drop/100))
                
                status = "🎯 BEREIT" if m['Preis'] <= t1_price or m['Preis'] <= t2_price else "⏳ Warten"
                
                m_data.append({
                    "Ticker": r['ticker'],
                    "Name": m['Name'],
                    "Kurs": m['Preis'],
                    "Fair Value": r['fair_value'],
                    "Tranche 1 (MoS)": round(t1_price, 2),
                    "Tranche 2 (ATH-Korr)": round(t2_price, 2),
                    "Abstand ATH %": m['ATH_Dist'],
                    "Ø Perf %": m['Avg_Perf'],
                    "Trend": m['Trend'],
                    "RSI": m['RSI'],
                    "Status": status
                })

    if m_data:
        df_final = pd.DataFrame(m_data)
        
        # Ansicht 1 & 2: Sparplan / Tranche
        if "ATH-Korrektur" not in view_option:
            st.subheader(f"📋 {view_option} Übersicht")
            # Spalten: Kurs, Fair Value, Tranche 1, Tranche 2
            cols_to_show = ["Ticker", "Name", "Kurs", "Fair Value", "Tranche 1 (MoS)", "Tranche 2 (ATH-Korr)", "Status"]
            st.dataframe(df_final[cols_to_show].style.apply(lambda x: ['background-color: #004d00' if "🎯" in str(x.Status) else '' for i in x], axis=1), use_container_width=True, hide_index=True)
        
        # Ansicht 3: ATH & Durchschnitts-Check
        else:
            st.subheader("📉 Allzeithoch-Korrekturen & Performance-Check (Alle)")
            cols_to_show = ["Ticker", "Name", "Kurs", "Abstand ATH %", "Ø Perf %", "RSI", "Trend"]
            st.dataframe(df_final[cols_to_show].sort_values("Abstand ATH %"), use_container_width=True, hide_index=True)

        # --- KI ANALYSE ---
        st.divider()
        ki_ticker = st.selectbox("KI Analyse für:", df_final['Ticker'].tolist())
        if st.button("KI Analyse starten"):
            row = df_final[df_final['Ticker'] == ki_ticker].iloc[0]
            prompt = f"Analyse für {ki_ticker}. Kurs {row['Kurs']}, Fair Value {row['Fair Value']}, Korrektur vom ATH: {row['Abstand ATH %']}%. Trend: {row['Trend']}. Lohnt sich ein Einstieg?"
            with st.chat_message("assistant"):
                st.markdown(ki_model.generate_content(prompt).text)

else:
    st.info("Keine Daten vorhanden. Nutze die Sidebar zum Hinzufügen.")
