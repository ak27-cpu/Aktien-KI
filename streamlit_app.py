import streamlit as st
from supabase import create_client, Client
import yfinance as yf
import pandas as pd
import google.generativeai as genai

# --- 1. KONFIGURATION & SETUP ---
st.set_page_config(page_title="KI Aktien-Terminal", layout="wide")

# KI Setup
# --- KI SETUP (AKTUALISIERT) ---
if "gemini_key" in st.secrets:
    genai.configure(api_key=st.secrets["gemini_key"])
    # Wir nutzen das neueste Modell aus deiner Liste
    ki_model = genai.GenerativeModel('models/gemini-2.5-flash')
else:
    st.error("Gemini API Key fehlt in den Secrets!")

def ask_ki(prompt):
    try:
        # Sicherheits-Check: Falls das Modell eine Antwort verweigert
        response = ki_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"KI-Fehler: {str(e)}. Versuche es in einem Moment erneut."

# Supabase Setup
@st.cache_resource
def get_supabase():
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

supabase = get_supabase()
# --- DEBUG: WELCHE MODELLE SIND VERFÜGBAR? ---
with st.expander("🛠️ KI-System-Check (Nur bei Fehlern nutzen)"):
    if st.button("Verfügbare Modelle auflisten"):
        try:
            available_models = genai.list_models()
            models_list = [m.name for m in available_models if 'generateContent' in m.supported_generation_methods]
            st.write("Dein Key unterstützt folgende Modelle:")
            st.json(models_list)
        except Exception as e:
            st.error(f"Fehler beim Abrufen der Modelle: {e}")

# --- 2. FUNKTIONEN ---
def load_watchlist():
    res = supabase.table("watchlist").select("*").execute()
    return pd.DataFrame(res.data)

@st.cache_data(ttl=3600)
def get_live_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="2y")
        price = info.get('currentPrice') or hist['Close'].iloc[-1]
        sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        return {
            "Kurs": round(price, 2),
            "Schulden_Quote": round(info.get('debtToEquity', 0) / 100 if info.get('debtToEquity', 0) > 2 else info.get('debtToEquity', 0), 2),
            "Trend": "Aufwärts ✅" if price > sma200 else "Abwärts ⚠️",
            "KGV": info.get('trailingPE', 'N/A')
        }
    except: return None

def ask_ki(prompt):
    try:
        response = ki_model.generate_content(prompt)
        return response.text
    except Exception as e: return f"Fehler: {e}"

# --- 3. HAUPT-UI ---
st.title("🚀 Mein KI-Aktien-Terminal")

# Sidebar: Verwaltung
with st.sidebar:
    st.header("➕ Watchlist")
    t_input = st.text_input("Ticker").upper()
    fv_input = st.number_input("Fair Value", value=0.0)
    if st.button("Hinzufügen"):
        supabase.table("watchlist").insert({"ticker": t_input, "fair_value": fv_input}).execute()
        st.rerun()

# Daten laden
df_db = load_watchlist()

if not df_db.empty:
    # Live-Daten mischen
    with st.spinner("Lade Marktdaten..."):
        all_data = []
        for _, row in df_db.iterrows():
            live = get_live_data(row['ticker'])
            if live: all_data.append({**row, **live})
    
    df_final = pd.DataFrame(all_data)
    st.dataframe(df_final, use_container_width=True, hide_index=True)

    st.divider()

    # --- KI ANALYSE BEREICH ---
    st.subheader("🤖 KI Analysten-Terminal")
    
    sel_ticker = st.selectbox("Aktie wählen:", df_final['ticker'])
    modus = st.radio("Analyse-Typ:", [
        "Komplett-Analyse", "Bewertungs-Profi", "Dividenden-Check", 
        "Konkurrenz-Vergleich", "Crash-Analyse", "Portfolio-Check"
    ], horizontal=True)

    # Hier greift dein Experten-Regelwerk
    if st.button(f"Analyse für {sel_ticker} starten"):
        stock_info = df_final[df_final['ticker'] == sel_ticker].iloc[0].to_dict()
        
        prompts = {
            "Komplett-Analyse": f"Analysiere {sel_ticker} wie ein Profi-Equity-Analyst: 1. Geschäftsmodell, 2. Fundamentaldaten, 3. Bewertung, 4. Bilanz, 5. Dividende, 6. Chancen/Risiken, 7. Szenarien, 8. Fazit. Daten: {stock_info}",
            "Bewertungs-Profi": f"Berechne fairen Wert für {sel_ticker} via DCF, Multiples & Branchenvergleich. Daten: {stock_info}",
            "Dividenden-Check": f"Prüfe Dividendenqualität von {sel_ticker}: Quote, Historie, Sicherheit. Urteil: sicher, fraglich, riskant.",
            "Konkurrenz-Vergleich": f"Vergleiche {sel_ticker} mit 3 Konkurrenten (Wachstum, Margen, Burggraben). Erstelle Ranking.",
            "Crash-Analyse": f"Historisches Verhalten von {sel_ticker} in Krisen. Stabilität 1-10.",
            "Portfolio-Check": f"Bewerte mein Portfolio: {df_final['ticker'].tolist()}. Fokus auf Klumpenrisiken & Optimierung."
        }
        
        with st.chat_message("assistant"):
            bericht = ask_ki(prompts[modus])
            st.markdown(bericht)
else:
    st.info("Noch keine Ticker in der Datenbank.")
