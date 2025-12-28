import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta
import json

# --- 1. SETUP ---
st.set_page_config(page_title="Ultimate Cockpit v16", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Setup Fehler: {e}")
    st.stop()

# --- 2. KI FUNKTION FÜR AUTOMATISCHEN FAIR VALUE ---
def get_ai_fair_value(ticker, info, current_price):
    """Fragt die KI nach einer fairen Bewertung, falls kein manueller Wert vorliegt."""
    prompt = f"""
    Analysiere die Aktie {ticker}. 
    Aktueller Kurs: {current_price}
    Sektor: {info.get('sector')}
    KGV (Trailing): {info.get('trailingPE')}
    Dividendenrendite: {info.get('dividendYield')}
    
    Gib NUR eine Zahl als Antwort zurück, die den geschätzten fairen Wert (Innerer Wert) repräsentiert. 
    Keinen Text, nur die Zahl.
    """
    try:
        response = ki_model.generate_content(prompt)
        # Extrahiere nur die Zahl aus der Antwort
        val = "".join(c for c in response.text if c.isdigit() or c == '.')
        return round(float(val), 2)
    except:
        return round(current_price * 0.9, 2) # Fallback: 10% unter Kurs

# --- 3. DATEN-FUNKTIONEN ---
@st.cache_data(ttl=1800)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="3y")
        if h.empty: return None
        info = s.info
        cp = h['Close'].iloc[-1]
        
        # Drawdown & Performance
        roll_max = h['High'].cummax()
        avg_drawdown = round(((h['Low'] - roll_max) / roll_max).mean() * 100, 2)
        
        def get_perf(d):
            idx = h.index.get_indexer([h.index[-1] - timedelta(days=d)], method='nearest')[0]
            return round(((cp / h['Close'].iloc[idx]) - 1) * 100, 2)

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'Unbekannt'),
            "Preis": round(cp, 2),
            "ATH": round(h['High'].max(), 2),
            "ATH_Dist": round(((cp / h['High'].max()) - 1) * 100, 1),
            "Avg_Korrektur": avg_drawdown,
            "RSI": round((lambda d: 100 - (100 / (1 + (d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))).iloc[-1])(h['Close'].diff()), 1),
            "Trend": "Bull 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Bear 📉",
            "KGV": info.get('trailingPE', 0),
            "Div": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0,
            "Perf": {"1M": get_perf(30), "1Y": get_perf(365)},
            "raw_info": info # Für KI
        }
    except: return None

# --- 4. DATEN LADEN & SIDEBAR ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

with st.sidebar:
    st.header("⚙️ Management")
    view = st.radio("Ansicht:", ["Alle", "Tranche", "Sparplan"])
    st.divider()
    base_mos = st.slider("Margin of Safety % (T1)", 0, 50, 15)
    t2_drop = st.slider("ATH-Korrektur % (T2)", 10, 60, 30)
    
    with st.expander("➕ Aktie hinzufügen"):
        with st.form("add"):
            t = st.text_input("Ticker").upper()
            f = st.number_input("Manueller Fair Value (0 = KI Automatik)", min_value=0.0)
            typ = st.selectbox("Typ", ["Tranche", "Sparplan"])
            if st.form_submit_button("OK"):
                supabase.table("watchlist").insert({"ticker": t, "fair_value": f if f > 0 else None, "watchlist_type": typ}).execute()
                st.rerun()

# --- 5. DASHBOARD ---
st.title(f"🏛️ Smart Cockpit: {view}")

if not df_db.empty:
    df_show = df_db if view == "Alle" else df_db[df_db['watchlist_type'].str.lower() == view.lower()]

    m_data = []
    with st.spinner("KI & Marktdaten werden synchronisiert..."):
        for _, r in df_show.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                # Logik: Manueller Wert vs. KI Wert
                if r.get('fair_value') and float(r['fair_value']) > 0:
                    fv = float(r['fair_value'])
                    fv_type = "Manuell"
                else:
                    fv = get_ai_fair_value(r['ticker'], m['raw_info'], m['Preis'])
                    fv_type = "🤖 KI"
                
                t1 = fv * (1 - (base_mos/100))
                t2 = m['ATH'] * (1 - (t2_drop/100))
                status = "🎯 BEREIT" if (m['Preis'] <= t1 or m['Preis'] <= t2) else "⏳ Warten"
                
                m_data.append({
                    "Ticker": r['ticker'], "Name": m['Name'], "Kurs": m['Preis'], 
                    "Fair Value": fv, "Typ": fv_type, "T1 (MoS)": round(t1, 2), "T2 (ATH)": round(t2, 2),
                    "Korr %": m['ATH_Dist'], "RSI": m['RSI'], "Status": status, "Sektor": m['Sektor']
                })

    if m_data:
        df = pd.DataFrame(m_data)
        tab1, tab2 = st.tabs(["🎯 Strategie & Einstieg", "📊 Marktanalyse"])
        
        with tab1:
            st.dataframe(df[["Ticker", "Kurs", "Fair Value", "Typ", "T1 (MoS)", "T2 (ATH)", "Status"]].style.apply(
                lambda x: ['background-color: #004d00' if "🎯" in str(x.Status) else '' for i in x], axis=1), 
                use_container_width=True, hide_index=True)
        with tab2:
            st.dataframe(df[["Ticker", "Name", "Sektor", "Korr %", "RSI"]], use_container_width=True, hide_index=True)
