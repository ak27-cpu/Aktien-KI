import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. SETUP ---
st.set_page_config(page_title="Ultimate Cockpit v17", layout="wide")

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Setup Fehler: {e}")
    st.stop()

# --- 2. KI FAIR VALUE LOGIK ---
def get_ai_fair_value(ticker, info, current_price):
    prompt = f"Analysiere {ticker}. Preis: {current_price}, KGV: {info.get('trailingPE')}. Gib NUR den fairen Wert als Zahl zurück."
    try:
        response = ki_model.generate_content(prompt)
        val = "".join(c for c in response.text if c.isdigit() or c == '.')
        return float(val)
    except:
        return current_price * 0.95

# --- 3. METRIKEN LADEN ---
@st.cache_data(ttl=1800)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="3y")
        if h.empty: return None
        info = s.info
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        
        # Durchschnittlicher Drawdown
        roll_max = h['High'].cummax()
        avg_dd = round(((h['Low'] - roll_max) / roll_max).mean() * 100, 2)

        return {
            "Name": info.get('longName', ticker),
            "Sektor": info.get('sector', 'N/A'),
            "Preis": round(cp, 2),
            "ATH": round(ath, 2),
            "ATH_Dist": round(((cp / ath) - 1) * 100, 1),
            "Avg_Korr": avg_dd,
            "RSI": round((lambda d: 100 - (100 / (1 + (d.where(d > 0, 0).rolling(14).mean() / (-d.where(d < 0, 0)).rolling(14).mean()))).iloc[-1])(h['Close'].diff()), 1),
            "Trend": "Bull 📈" if cp > h['Close'].rolling(200).mean().iloc[-1] else "Bear 📉",
            "KGV": info.get('trailingPE', 0),
            "Div": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0,
            "raw_info": info
        }
    except: return None

# --- 4. DATEN LADEN & SIDEBAR ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

with st.sidebar:
    st.header("⚙️ Steuerung")
    view = st.radio("Ansicht:", ["Alle", "Tranche", "Sparplan"])
    st.divider()
    base_mos = st.slider("Margin of Safety % (T1)", 0, 50, 15)
    t2_drop = st.slider("ATH-Korrektur % (T2)", 10, 60, 30)
    
    with st.expander("🗑️ Aktie löschen"):
        if not df_db.empty:
            target = st.selectbox("Ticker", ["-"] + sorted(df_db['ticker'].tolist()))
            if st.button("Löschen") and target != "-":
                supabase.table("watchlist").delete().eq("ticker", target).execute()
                st.rerun()

# --- 5. HAUPTANZEIGE ---
st.title(f"🏛️ Smart Investment Cockpit")

if not df_db.empty:
    df_filtered = df_db if view == "Alle" else df_db[df_db['watchlist_type'].str.lower() == view.lower()]

    final_rows = []
    with st.spinner("Berechne Fair Values..."):
        for _, row in df_filtered.iterrows():
            m = get_metrics(row['ticker'])
            if m:
                # SICHERHEITS-CHECK: Fair Value Typ-Umwandlung
                try:
                    val_db = row.get('fair_value')
                    manual_fv = float(val_db) if val_db is not None and str(val_db).strip() != "" else 0.0
                except:
                    manual_fv = 0.0

                if manual_fv > 0:
                    fv, fv_type = manual_fv, "Manuell"
                else:
                    fv, fv_type = get_ai_fair_value(row['ticker'], m['raw_info'], m['Preis']), "🤖 KI"

                # Berechnung der Tranchen
                t1 = fv * (1 - (base_mos/100))
                t2 = m['ATH'] * (1 - (t2_drop/100))
                
                status = "🎯 BEREIT" if (m['Preis'] <= t1 or m['Preis'] <= t2) else "⏳ Warten"
                
                final_rows.append({
                    "Ticker": row['ticker'], "Sektor": m['Sektor'], "Kurs": m['Preis'],
                    "Fair Value": round(fv, 2), "Typ": fv_type, "T1 (MoS)": round(t1, 2),
                    "T2 (ATH)": round(t2, 2), "Korr %": m['ATH_Dist'], "Ø Korr %": m['Avg_Korr'],
                    "RSI": m['RSI'], "Trend": m['Trend'], "Status": status
                })

    if final_rows:
        df_final = pd.DataFrame(final_rows)
        t_strat, t_markt = st.tabs(["🎯 Strategie", "📊 Markt & Technik"])
        
        with t_strat:
            st.dataframe(df_final[["Ticker", "Kurs", "Fair Value", "Typ", "T1 (MoS)", "T2 (ATH)", "Status"]].style.apply(
                lambda x: ['background-color: #004d00' if "🎯" in str(x.Status) else '' for i in x], axis=1), 
                use_container_width=True, hide_index=True)
        
        with t_markt:
            st.dataframe(df_final[["Ticker", "Sektor", "Korr %", "Ø Korr %", "RSI", "Trend"]], use_container_width=True, hide_index=True)
else:
    st.info("Keine Aktien gefunden.")
