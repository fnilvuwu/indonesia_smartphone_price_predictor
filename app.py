import streamlit as st
import pandas as pd
import numpy as np
import joblib

# Set page configuration
st.set_page_config(
    page_title="Smartphone Price Predictor",
    page_icon="📱",
    layout="wide"
)

# Load the model and scaler
@st.cache_resource
def load_model():
    try:
        model = joblib.load('smartphone_price_prediction_model.pkl')
        scaler = joblib.load('smartphone_price_scaler.pkl')
        return model, scaler
    except FileNotFoundError:
        st.error("❌ Model files not found. Please make sure the model has been trained and saved.")
        return None, None

# Load brand mapping
@st.cache_data
def load_brand_mapping():
    try:
        brand_df = pd.read_csv('brand_mapping.csv')
        return brand_df
    except FileNotFoundError:
        st.error("❌ Brand mapping file not found.")
        return pd.DataFrame({'Brand': ['Unknown'], 'BrandID': [0]})

# Load the model and brand mapping
model, scaler = load_model()
brand_df = load_brand_mapping()

# Function to make predictions
def predict_price(features):
    input_df = pd.DataFrame([features])
    
    if model is None or scaler is None:
        return None
    
    # Lakukan scaling jika diperlukan
    if hasattr(model, 'coef_'):
        input_scaled = scaler.transform(input_df)
        prediction = model.predict(input_scaled)[0]
    else:
        prediction = model.predict(input_df)[0]
    
    # Kembalikan dari log transformasi
    prediction = np.expm1(prediction)
    
    return prediction

# Main app layout
st.title("📱 Smartphone Price Predictor")

# Panduan Penggunaan
with st.expander("ℹ Panduan Penggunaan"):
    st.write("""
    **Cara menggunakan aplikasi ini:**
    1. Pilih merek smartphone.
    2. Atur spesifikasi seperti RAM, Storage, Kamera, dll.
    3. Klik tombol **Predict Price** untuk mendapatkan perkiraan harga.
    4. Hasil prediksi akan muncul dengan detail spesifikasi yang Anda masukkan.
    """)

# Layout kolom
col1, col2 = st.columns([2, 3])

with col1:
    st.header("🛠 Masukkan Spesifikasi Smartphone")
    
    brand = st.selectbox("📌 Brand", options=brand_df['Brand'].tolist(), index=2)
    brand_id = brand_df[brand_df['Brand'] == brand]['BrandID'].values[0]
    
    ram = st.slider("💾 RAM (GB)", 1, 24, 8, 1)
    storage = st.slider("💾 Storage (GB)", 1, 512, 128, 1)
    camera = st.slider("📷 Main Camera (MP)", 1, 200, 64, 1)
    screen_size = st.slider("📱 Screen Size (inches)", 4.0, 8.0, 6.5, 0.1)
    battery = st.slider("🔋 Battery Capacity (mAh)", 1000, 10000, 5000, 100)
    release_year = st.slider("📆 Release Year", 2015, 2025, 2023, 1)
    
    predict_button = st.button("🔮 Predict Price")

with col2:
    st.header("📊 Hasil Prediksi")
    
    if predict_button:
        features = {
            'RAM': float(ram),
            'Storage': float(storage),
            'Camera': float(camera),
            'ScreenSize': float(screen_size),
            'Battery': float(battery),
            'ReleaseYear': float(release_year),
            'BrandID': float(brand_id)
        }
        
        prediction = predict_price(features)
        
        if prediction is not None:
            st.markdown(f"""
            ### **📢 Prediction for a {brand} phone**
            - **RAM**: {int(ram)}GB  
            - **Storage**: {int(storage)}GB  
            - **Camera**: {int(camera)}MP  
            - **Screen Size**: {screen_size} inches  
            - **Battery**: {int(battery)}mAh  
            - **Release Year**: {int(release_year)}
            
            ### 💰 **Predicted Price: Rp {int(prediction):,}**
            """, unsafe_allow_html=True)
        else:
            st.error("❌ Model or scaler is not loaded correctly.")
    
    else:
        st.info("🔎 **Masukkan spesifikasi smartphone Anda di sebelah kiri dan tekan tombol 'Predict Price' untuk melihat estimasi harga.**")  
