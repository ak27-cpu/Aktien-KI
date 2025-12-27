import streamlit as st
from supabase import create_client
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai

# --- 1. SETUP & KONFIGURATION ---
st.set_page_config(page_title="Investment Terminal 2025", layout="wide")

# KI Setup
if "gemini_key" in st.secrets:
    genai.configure(api_key=st.secrets["gemini_key"])
    ki_model = genai.GenerativeModel('models/gemini-2.5-flash')
else:
    st.error("API Key fehlt!")
    st.stop()

# Supabase Verbindung
supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

# --- 2. FUNKTIONEN ---

def ask_ki(prompt):
    try:
        response = ki_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"KI-Fehler: {e}"

@st.cache_data(ttl=3600)
def get_metrics(ticker):
    try:
        s = yf.Ticker(ticker)
        h = s.history(period="1y")
        if h.empty: return None
        
        info = s.info
        cp = info.get('currentPrice') or h['Close'].iloc[-1]
        
        # RSI Berechnung
        delta = h['Close'].diff()
        g = delta.where(delta > 0, 0).rolling(window=14).mean()
        l = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + (g/l))).iloc[-1]
        
        # Schulden & Korrektur
        d2e = info.get('debtToEquity', 0) or 0
        debt = d2e if d2e > 5 else d2e * 100
        korr = ((cp / h['High'].max()) - 1) * 100
        
        return {
            "Preis": round(cp, 2), 
            "RSI": round(rsi, 1), 
            "Schulden": round(debt, 1), 
            "Korr": round(korr, 1)
        }
    except: return None

# --- 3. HAUPT-ANWENDUNG ---

st.title("🏛️ Professional Investment Terminal Pro")

# Daten aus Supabase laden
res = supabase.table("watchlist").select("*").execute()
df_db = pd.DataFrame(res.data)

# --- SIDEBAR: MANAGEMENT ---
with st.sidebar:
    st.header("➕ Aktie hinzufügen")
    t_in = st.text_input("Ticker Symbol").upper()
    fv_in = st.number_input("Fair Value (€) - 0 = KI Check", value=0.0)
    
    if st.button("Speichern"):
        if t_in:
            with st.spinner(f"Analysiere {t_in}..."):
                m_temp = get_metrics(t_in)
                final_fv = fv_in
                
                # Automatischer Fair Value via KI
                if final_fv <= 0 and m_temp:
                    prompt = f"Berechne basierend auf Kurs {m_temp['Preis']}€ einen fairen Wert für {t_in}. Gib NUR die Zahl zurück."
                    res_ki = ask_ki(prompt)
                    try:
                        cleaned = "".join(filter(lambda x: x.isdigit() or x == '.', res_ki))
                        final_fv = float(cleaned)
                    except:
                        final_fv = m_temp['Preis'] * 0.9
                
                supabase.table("watchlist").insert({"ticker": t_in, "fair_value": final_fv}).execute()
                st.success(f"{t_in} gespeichert.")
                st.rerun()

    st.divider()
    st.header("⚙️ Kauf-Parameter")
    t_spread = st.slider("Abstand Tranche 2 (%)", 5, 25, 12)
    rsi_limit = st.slider("Max. RSI für Kaufzone", 30, 70, 45)

# --- 4. DASHBOARD ANZEIGE ---
if not df_db.empty:
    rows = []
    with st.spinner("Marktdaten werden aktualisiert..."):
        for _, r in df_db.iterrows():
            m = get_metrics(r['ticker'])
            if m:
                # Sicherheits-Check für Fair Value
                fv = r.get('fair_value', 0) or 0
                abstand = ((m['Preis'] / fv) - 1) * 100 if fv > 0 else 0
                
                # Tranchen & Status
                status = "🎯 KAUFZONE" if fv > 0 and m['Preis'] <= fv and m['RSI'] <= rsi_limit else "⏳ Warten"
                t2_preis = fv * (1 - t_spread/100) if fv > 0 else 0
                
                rows.append({
                    "id": r['id'],
                    "Ticker": r['ticker'],
                    "Kurs": m['Preis'],
                    "Fair_Value": fv,
                    "Abstand_%": round(abstand, 1),
                    "RSI": m['RSI'],
                    "Schulden_%": m['Schulden'],
                    "Status": status,
                    "Tranche_2": round(t2_preis, 2)
                })

    df_display = pd.DataFrame(rows)

    # Editierbare Watchlist
    st.subheader("📊 Live Markt-Monitor & Tranchen-Planer")
    
    # Editor für Fair Value Änderungen
    edited_df = st.data_editor(
        df_display,
        column_config={
            "id": None,
            "Fair_Value": st.column_config.NumberColumn("Fair Value (€)", format="%.2f"),
            "Status": st.column_config.TextColumn("Signal"),
            "Tranche_2": st.column_config.NumberColumn("Tranche 2 (€)")
        },
        disabled=["Ticker", "Kurs", "Abstand_%", "RSI", "Schulden_%", "Status", "Tranche_2"],
        hide_index=True,
        use_container_width=True
    )

    # Speichern von Änderungen
    if st.button("💾 Alle Änderungen permanent speichern"):
        for _, row in edited_df.iterrows():
            supabase.table("watchlist").update({"fair_value": row["Fair_Value"]}).eq("id", row["id"]).execute()
        st.success("Datenbank aktualisiert!")
        st.rerun()

    # Löschen Sektion
    with st.expander("🗑️ Ticker aus Watchlist löschen"):
        del_ticker = st.selectbox("Wähle Ticker zum Entfernen", df_display['Ticker'])
        if st.button("Endgültig Löschen"):
            supabase.table("watchlist").delete().eq("ticker", del_ticker).execute()
            st.rerun()

    # --- 5. KI DEEP DIVE ---
    st.divider()
    st.subheader("🤖 Experten-Analyse & Fair Value Kalkulator")
    
    sel_ticker = st.selectbox("Aktie für Detail-Check wählen:", df_display['Ticker'])
    modus = st.radio("Analyse-Fokus:", ["Fair Value & Tranchen", "Bilanz & Risiko", "Konkurrenz & Ranking"], horizontal=True)
    
    if st.button("KI Analyse starten"):
        stock_context = df_display[df_display['Ticker'] == sel_ticker].iloc[0].to_dict()
        
        prompts = {
            "Fair Value & Tranchen": f"Berechne einen gemittelten Fair Value für {sel_ticker} (DCF + Multiples). Erstelle einen 3-Tranchen-Einstiegsplan basierend auf Kurs {stock_context['Kurs']}. Daten: {stock_context}",
            "Bilanz & Risiko": f"Analysiere Bilanzqualität und Verschuldung von {sel_ticker}. Wo liegen die größten Gefahren für das Geschäftsmodell?",
            "Konkurrenz & Ranking": f"Vergleiche {sel_ticker} mit den wichtigsten Wettbewerbern in Bezug auf Margen und Marktmacht."
        }
        
        with st.chat_message("assistant"):
            st.markdown(ask_ki(prompts[modus]))

else:
    st.info("Deine Watchlist ist leer. Füge in der Seitenleiste Ticker hinzu.")
