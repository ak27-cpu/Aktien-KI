import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP & KONFIGURATION ---
st.set_page_config(page_title="Investment Cockpit Ultimate v4", layout="wide")

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
        spy_obj = yf.Ticker("^GSPC")
        spy_hist = spy_obj.history(period="200d")
        cp = spy_hist['Close'].iloc[-1]
        sma125 = spy_hist['Close'].rolling(125).mean().iloc[-1]
        fg_score = int((cp / sma125) * 50)
        spy_perf_ytd = ((cp / spy_hist['Close'].iloc[0]) - 1) * 100
        return round(vix, 2), min(100, fg_score), spy_perf_ytd
    except: return 20.0, 50, 0.0

@st.cache_data(ttl=1800)
def get_ultimate_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="2y")
        if h.empty: return None
        info = s.info
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        vol_ratio = round(h['Volume'].iloc[-1] / h['Volume'].tail(20).mean(), 2)
        perf_1y = ((cp / h['Close'].iloc[-252]) - 1) * 100 if len(h) > 252 else 0
        sma200 = h['Close'].rolling(200).mean().iloc[-1]
        rsi = (lambda d: 100 - (100 / (1 + (d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))).iloc[-1])(h['Close'].diff())
        
        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "RSI": round(rsi, 1),
            "Trend": "Bull 📈" if cp > sma200 else "Bear 📉",
            "Vol_Ratio": vol_ratio,
            "Perf_1Y": round(perf_1y, 1),
            "KGV": info.get('trailingPE', 0),
            "Div": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0
        }
    except: return None

# --- 3. HEADER & DASHBOARD STATUS ---
vix, fg, spy_perf = get_market_indicators()
st.title("🏛️ Multi-Watchlist Cockpit")

# Banner Sektion
c1, c2, c3 = st.columns(3)
with c1:
    vix_status = "🚨 PANIK" if vix > 30 else ("⚠️ NERVÖS" if vix > 20 else "📉 RUHIG")
    st.metric("VIX Index", vix, vix_status, delta_color="inverse")
with c2:
    fg_status = "🔥 GIER" if fg > 70 else ("😱 ANGST" if fg < 30 else "⚖️ NEUTRAL")
    st.metric("Fear & Greed", f"{fg}/100", fg_status)
with c3:
    st.metric("S&P 500 Perf", f"{round(spy_perf, 1)}%", "Benchmark")

st.divider()

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Strategie-Zentrale")
    # Watchlist Auswahl
    selected_list = st.radio("📂 Watchlist wählen:", ["Alle", "Tranchen-Käufe", "Sparpläne"])
    
    st.divider()
    base_mos = st.slider("Margin of Safety (%)", 0, 50, 15)
    t1_drop = st.slider("Tranche 1 (ATH-Korr %)", 5, 50, 15)
    t2_drop = st.slider("Tranche 2 (ATH-Korr %)", 10, 70, 35)
    
    mos_adj = 10 if fg > 75 else (-5 if fg < 25 else 0)
    total_mos = base_mos + mos_adj
    st.info(f"Gesamt-MoS Ziel: {total_mos}%")
    
    if st.button("🔄 System Refresh"):
        st.cache_data.clear()
        st.rerun()

# --- 5. DATEN LADEN & FILTERN ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    # Filter-Logik
    if selected_list == "Tranchen-Käufe":
        df_db = df_db[df_db['watchlist_type'] == 'Tranche']
    elif selected_list == "Sparpläne":
        df_db = df_db[df_db['watchlist_type'] == 'Sparplan']

    m_list, s_list = [], []
    signals = 0
    
    with st.spinner(f"Lade {selected_list}..."):
        for _, r in df_db.iterrows():
            m = get_ultimate_metrics(r['ticker'])
            if m:
                adj_fv = r['fair_value'] * (1 - total_mos/100)
                t1_p = m['ATH'] * (1 - t1_drop/100)
                t2_p = m['ATH'] * (1 - t2_drop/100)
                
                status = "⏳ Warten"
                if m['Preis'] <= adj_fv and m['Preis'] <= t1_p: 
                    status = "🎯 TR1 BEREIT"; signals += 1
                if m['Preis'] <= t2_p: 
                    status = "🔥 TR2 LIMIT"; signals += 1
                
                # Tabelle 1
                m_list.append({
                    "Ticker": r['ticker'], "Name": m['Name'], "Kurs": m['Preis'], 
                    "Trend": m['Trend'], "RSI": m['RSI'], "Vol-Power": m['Vol_Ratio'],
                    "vs Markt %": round(m['Perf_1Y'] - spy_perf, 1), "KGV": m['KGV']
                })
                # Tabelle 2
                s_list.append({
                    "Ticker": r['ticker'], "Fair Value": r['fair_value'], "MoS-Preis": round(adj_fv, 2),
                    "Abstand T1 %": round(((m['Preis']/t1_p)-1)*100, 1), "Div %": m['Div'], "Status": status
                })

    if signals > 0 and selected_list != "Sparpläne":
        st.toast(f"🚨 {signals} Kauf-Signale!", icon="🎯")

    # Tabs für bessere Übersicht auf dem iPhone
    tab1, tab2 = st.tabs(["📊 Marktdaten", "🎯 Strategie & Kaufzonen"])

    with tab1:
        st.dataframe(pd.DataFrame(m_list), use_container_width=True, hide_index=True)

    with tab2:
        def style_final(row):
            color = '#004d00' if "🎯" in str(row['Status']) else ('#800000' if "🔥" in str(row['Status']) else '')
            return [f'background-color: {color}'] * len(row)
        
        st.dataframe(pd.DataFrame(s_list).style.apply(style_final, axis=1), use_container_width=True, hide_index=True)

    # --- 6. KI ANALYSE ---
    st.divider()
    if m_list:
        sel = st.selectbox("KI-Deep Dive Analyse:", [x['Ticker'] for x in m_list])
        if st.button("Analyse Report generieren"):
            m_ctx = next(i for i in m_list if i["Ticker"] == sel)
            s_ctx = next(i for i in s_list if i["Ticker"] == sel)
            prompt = f"Equity Report für {sel} aus der Liste {selected_list}. Markt: VIX {vix}. RSI {m_ctx['RSI']}. Status: {s_ctx['Status']}. Gib ein Fazit."
            with st.chat_message("assistant"):
                st.markdown(ki_model.generate_content(prompt).text)
else:
    st.info("Diese Watchlist ist aktuell leer.")
