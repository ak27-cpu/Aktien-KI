import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP ---
st.set_page_config(page_title="Investment Terminal 2025", layout="wide")

if "gemini_key" in st.secrets:
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.5-flash')
else:
    st.error("API Key fehlt!")
    st.stop()

supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

# --- 2. FUNKTIONEN ---

def ask_ki(prompt):
    try:
        return ki_model.generate_content(prompt).text
    except: return "KI Fehler"

def get_ki_fair_value(ticker, curr_price):
    """Generiert einen fairen Wert, falls 0 eingegeben wurde"""
    prompt = f"Berechne basierend auf aktuellen Marktdaten einen konservativen fairen Wert für die Aktie {ticker}. Aktueller Kurs: {curr_price}. Gib NUR die Zahl als Antwort, ohne Text."
    res = ask_ki(prompt)
    try:
        # Extrahiere nur die Zahl aus der Antwort
        return float(''.join(c for c in res if c.isdigit() or c == '.'))
    except: return round(curr_price * 0.9, 2) # Fallback: 10% unter Kurs

@st.cache_data(ttl=3600)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="1y")
        info = s.info
        cp = info.get('currentPrice') or h['Close'].iloc[-1]
        
        # RSI
        delta = h['Close'].diff(); g = delta.where(delta > 0, 0).rolling(14).mean(); l = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (g/l))).iloc[-1]
        
        # Schulden & Korrektur
        d2e = info.get('debtToEquity', 0) or 0
        debt = d2e if d2e > 5 else d2e * 100
        korr = ((cp / h['High'].max()) - 1) * 100
        
        return {"Preis": round(cp, 2), "RSI": round(rsi, 1), "Schulden": round(debt, 1), "Korr": round(korr, 1)}
    except: return None

# --- 3. DATEN & UI ---

st.title("🏛️ Professional Investment Terminal")

# Daten laden
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

# --- SIDEBAR: HINZUFÜGEN & KRITERIEN ---
with st.sidebar:
    st.header("➕ Neue Aktie")
    t_in = st.text_input("Ticker").upper()
    fv_in = st.number_input("Fair Value (0 = KI berechnet)", value=0.0)
    if st.button("Hinzufügen"):
        if t_in:
            if fv_in == 0:
                with st.spinner("KI berechnet fairen Wert..."):
                    m_temp = get_metrics(t_in)
                    fv_in = get_ki_fair_value(t_in, m_temp['Preis']) if m_temp else 0
            supabase.table("watchlist").insert({"ticker": t_in, "fair_value": fv_in}).execute()
            st.success(f"{t_in} hinzugefügt!")
            st.rerun()

    st.divider()
    st.header("⚙️ Kauf-Kriterien")
    tranchen_spread = st.slider("Tranchen-Abstand (%)", 5, 20, 10)
    max_rsi = st.slider("Max. RSI für Kauf", 30, 70, 45)

# --- HAUPTTEIL ---
if not df_db.empty:
    rows = []
    for _, r in df_db.iterrows():
        m = get_metrics(r['ticker'])
        if m:
            fv = r['fair_value']
            abstand = ((m['Preis'] / fv) - 1) * 100
            
            # Tranchen Logik
            t1 = fv
            t2 = fv * (1 - tranchen_spread/100)
            status = "🎯 KAUFZONE" if m['Preis'] <= fv and m['RSI'] <= max_rsi else "⏳ Warten"
            
            rows.append({
                "id": r['id'],
                "Ticker": r['ticker'],
                "Kurs": m['Preis'],
                "Fair Value": fv,
                "Abstand %": round(abstand, 1),
                "RSI": m['RSI'],
                "Schulden %": m['Schulden'],
                "Status": status,
                "Tranche 1": round(t1, 2),
                "Tranche 2": round(t2, 2)
            })

    df_display = pd.DataFrame(rows)

    # Editierbare Tabelle
    st.subheader("📊 Live Portfolio-Monitor")
    edited_df = st.data_editor(
        df_display, 
        column_config={
            "id": None, # ID verstecken
            "Fair Value": st.column_config.NumberColumn(format="%.2f €"),
            "Status": st.column_config.TextColumn("Empfehlung")
        },
        disabled=["Ticker", "Kurs", "Abstand %", "RSI", "Schulden %", "Tranche 1", "Tranche 2"],
        hide_index=True,
        use_container_width=True
    )

    # Änderungen in Supabase speichern
    if st.button("Änderungen in Datenbank übernehmen"):
        for _, row in edited_df.iterrows():
            supabase.table("watchlist").update({"fair_value": row["Fair Value"]}).eq("id", row["id"]).execute()
        st.success("Daten aktualisiert!")
        st.rerun()

    # Lösch-Funktion
    st.divider()
    del_col1, del_col2 = st.columns([3, 1])
    with del_col1:
        to_delete = st.selectbox("Aktie aus Liste entfernen:", df_display['Ticker'])
    with del_col2:
        if st.button("🗑️ Löschen"):
            supabase.table("watchlist").delete().eq("ticker", to_delete).execute()
            st.rerun()

    # --- KI ANALYSE ---
    st.divider()
    st.subheader("🤖 KI Fair-Value-Rechner & Deep Dive")
    sel_ticker = st.selectbox("Aktie für detaillierte Analyse wählen:", df_display['Ticker'])
    
    if st.button("Deep Dive & Fair Value Check starten"):
        stock_data = df_display[df_display['Ticker'] == sel_ticker].iloc[0].to_dict()
        prompt = f"""Analysiere {sel_ticker} extrem detailliert.
        1. Berechne einen gemittelten Fair Value aus DCF, KGV-Historie und Peer-Group.
        2. Vergleiche diesen mit meinem Wert ({stock_data['Fair Value']}€).
        3. Erstelle einen Kaufplan mit 3 Tranchen (Einstiegskurse).
        4. Risiko-Check: Bilanz & Markt.
        Daten: {stock_info}"""
        
        with st.chat_message("assistant"):
            st.markdown(ask_ki(prompt))
