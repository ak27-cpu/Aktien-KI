import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP & KONFIGURATION ---
st.set_page_config(page_title="Investment Terminal 2025", layout="wide")

# API Keys aus st.secrets laden
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.0-flash')
except Exception as e:
    st.error(f"Setup Fehler: {e}")
    st.stop()

# --- 2. HILFSFUNKTIONEN ---

def get_market_indicators():
    try:
        # VIX Index
        vix = yf.Ticker("^VIX")
        vix_val = vix.history(period="1d")['Close'].iloc[-1]
        
        # S&P 500 für Fear & Greed Proxy
        spy = yf.Ticker("^GSPC")
        spy_hist = spy.history(period="150d")
        cp = spy_hist['Close'].iloc[-1]
        sma125 = spy_hist['Close'].rolling(125).mean().iloc[-1]
        fg_score = int((cp / sma125) * 50)
        if fg_score > 100: fg_score = 100
        
        return round(vix_val, 2), fg_score
    except:
        return 20.0, 50

@st.cache_data(ttl=1800)
def get_stock_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="2y")
        if h.empty: return None
        cp = h['Close'].iloc[-1]
        ath = h['High'].max()
        
        # RSI 14 Tage
        delta = h['Close'].diff()
        g = delta.where(delta > 0, 0).rolling(window=14).mean()
        l = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + (g/l))).iloc[-1]
        
        return {"Preis": round(cp, 2), "ATH": round(ath, 2), "RSI": round(rsi, 1)}
    except:
        return None

# --- 3. HEADER: DYNAMISCHE BANNER ---
vix, fg = get_market_indicators()

st.title("🏛️ Investment Cockpit Pro")
col_vix, col_fg = st.columns(2)

with col_vix:
    if vix < 20:
        st.success(f"📉 VIX: {vix} (Ruhe)")
    elif 20 <= vix < 30:
        st.warning(f"⚠️ VIX: {vix} (Nervosität)")
    else:
        st.error(f"🚨 VIX: {vix} (PANIK)")

with col_fg:
    if fg < 35:
        st.success(f"😱 Fear & Greed: {fg}/100 (KAUFCHANCE)")
    elif 35 <= fg < 70:
        st.info(f"⚖️ Fear & Greed: {fg}/100 (Neutral)")
    else:
        st.error(f"🔥 Fear & Greed: {fg}/100 (VORSICHT)")

st.divider()

# --- 4. SIDEBAR MIT MARGIN OF SAFETY ---
with st.sidebar:
    st.header("⚙️ Strategie & Risiko")
    
    # NEU: Dynamische Margin of Safety
    st.subheader("🛡️ Margin of Safety")
    base_mos = st.slider("Basis MoS (%)", 0, 50, 10, help="Zusätzlicher Puffer unter deinem fairen Wert.")
    
    # Dynamische Empfehlung basierend auf Marktstimmung
    market_extra = 0
    if fg > 70: market_extra = 10  # Markt ist teuer, mehr Puffer
    if fg < 30: market_extra = -5  # Markt ist billig, weniger Puffer nötig
    
    total_mos = base_mos + market_extra
    st.info(f"Gesamt-MoS: {total_mos}% (inkl. Marktanpassung)")
    
    st.divider()
    t1_drop = st.slider("Tranche 1 (Korr. vom ATH %)", 5, 50, 15)
    rsi_limit = st.slider("Max. RSI für Kauf", 20, 70, 45)
    
    if st.button("🔄 Markt synchronisieren"):
        st.cache_data.clear()
        st.rerun()

# --- 5. HAUPT-LOGIK ---
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

if not df_db.empty:
    rows = []
    with st.spinner("Analysiere Daten..."):
        for _, r in df_db.iterrows():
            m = get_stock_metrics(r['ticker'])
            if m:
                fv_basis = r.get('fair_value', 0) or 0
                
                # Berechnung des MoS-adjustierten Fairen Werts
                adjusted_fv = fv_basis * (1 - (total_mos / 100))
                
                t1_p = m['ATH'] * (1 - t1_drop/100)
                
                # Signal Logik: Kurs muss UNTER dem adjustierten FV UND unter Tranche 1 sein
                status = "⏳ Warten"
                if m['Preis'] <= adjusted_fv and m['Preis'] <= t1_p:
                    status = "🎯 KAUFZONE" if m['RSI'] <= rsi_limit else "⚠️ RSI HOCH"
                elif m['Preis'] <= t1_p:
                    status = "🔍 Kurs OK, über MoS-FV"

                rows.append({
                    "Ticker": r['ticker'],
                    "Kurs": m['Preis'],
                    "Fair Value": fv_basis,
                    "MoS-FV": round(adjusted_fv, 2),
                    "RSI": m['RSI'],
                    "Korr/ATH %": round(((m['Preis']/m['ATH'])-1)*100, 1),
                    "Status": status
                })

    df_final = pd.DataFrame(rows)

    def style_status(val):
        if "🎯" in val: return 'background-color: #004d00; color: white'
        if "⚠️" in val: return 'background-color: #4d4d00; color: white'
        return ''

    st.subheader(f"📊 Live Watchlist (MoS: {total_mos}%)")
    st.dataframe(df_final.style.applymap(style_status, subset=['Status']), use_container_width=True, hide_index=True)

    # --- 6. KI ANALYSE ---
    st.divider()
    sel_ticker = st.selectbox("Aktie prüfen:", df_final['Ticker'])
    if st.button("KI-Check starten"):
        ctx = df_final[df_final['Ticker'] == sel_ticker].iloc[0].to_dict()
        prompt = f"Analysiere {sel_ticker}. Markt: VIX {vix}, F&G {fg}. MoS-FV liegt bei {ctx['MoS-FV']}. Gib ein Fazit."
        with st.chat_message("assistant"):
            st.markdown(ki_model.generate_content(prompt).text)
