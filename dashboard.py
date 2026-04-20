import streamlit as st
import pandas as pd
import json
import yfinance as yf
import plotly.graph_objects as go
import boto3
from dotenv import load_dotenv
import os

load_dotenv()

access_key = os.getenv('aws_access_key_id')
secret_access_key = os.getenv('aws_secret_access_key')

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Target Analysis Dashboard", layout="wide")
st.title("Target Hit Analysis")
st.markdown("Track target achievements and visualize live price action against your trade setup.")

# --- S3 DATA FETCHING (DUMMY CODE) ---
@st.cache_data(ttl=600) # Cache the S3 data for 10 minutes
def fetch_json_from_s3(bucket_name, object_key):
    """
    Fetches and parses a JSON file from an AWS S3 bucket.
    Ensure your AWS credentials are set up in your environment 
    (e.g., via `aws configure` or environment variables).
    """
    try:
        # Initialize the S3 client
        s3 = boto3.client('s3', region_name='us-east-1', aws_access_key_id=access_key, aws_secret_access_key=secret_access_key)
        
        # Fetch the object from the bucket
        response = s3.get_object(Bucket=bucket_name, Key=object_key)
        
        # Read the streaming body and decode it
        file_content = response['Body'].read().decode('utf-8')
        
        # Parse and return the JSON
        return json.loads(file_content)
        
    except Exception as e:
        st.error(f"Failed to fetch data from S3. Error: {e}")
        st.stop() # Stops execution if S3 fails

# --- HELPER: LIVE PRICE FETCHER ---
@st.cache_data(ttl=300)
def get_live_price(ticker):
    """Fetches the latest close price from Yahoo Finance. Appends .NS for Indian stocks."""
    try:
        yf_ticker = f"{ticker}.NS" 
        stock = yf.Ticker(yf_ticker)
        hist = stock.history(period="1d")
        if not hist.empty:
            return round(hist['Close'].iloc[-1], 2)
        return None
    except Exception as e:
        return None

# --- DATA LOADING & PROCESSING ---
def load_data(json_data):
    data = []
    
    if isinstance(json_data, list):
        items = [(k, v) for d in json_data for k, v in d.items()]
    else:
        items = json_data.items()

    for ticker, details in items:
        if not isinstance(details, dict): continue
            
        targets = details.get("targets") or {}
        hit_dates = details.get("hit_dates") or {}
        
        data.append({
            "Ticker": ticker,
            "Entry": details.get("entry_price"),
            "Stop Loss": details.get("stop_loss"),
            "T1": targets.get("T1"),
            "T2": targets.get("T2"),
            "T3": targets.get("T3"),
            "T1_Date": hit_dates.get("T1"),
            "T2_Date": hit_dates.get("T2"),
            "T3_Date": hit_dates.get("T3"),
            "Days": details.get("days_tracked", 0)
        })
        
    return pd.DataFrame(data)


# ==========================================
# MAIN APP EXECUTION
# ==========================================

# 1. Configuration for S3 (Replace these with your actual bucket details later)
BUCKET_NAME = "swapnil-miscellaneous"
FILE_KEY = "target_tracker/target.json"

# 2. Fetch and Load Data
with st.spinner("Fetching data from S3..."):
    parsed_json = fetch_json_from_s3(BUCKET_NAME, FILE_KEY)
    
if parsed_json:
    df = load_data(parsed_json)
else:
    st.warning("No data returned from S3.")
    st.stop()

# --- 1. KPI CARDS ---
st.markdown("### Overall Target Performance")

total_stocks = len(df)
t1_met = len(df[df['T1_Date'].notna()])
t2_eligible = len(df[df['T2'].notna()])
t2_met = len(df[df['T2_Date'].notna()])
t3_eligible = len(df[df['T3'].notna()])
t3_met = len(df[df['T3_Date'].notna()])

kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric("T1 Targets Met", f"{t1_met} / {total_stocks}")
kpi2.metric("T2 Targets Met (Where Applicable)", f"{t2_met} / {t2_eligible}" if t2_eligible > 0 else "0 / 0")
kpi3.metric("T3 Targets Met (Where Applicable)", f"{t3_met} / {t3_eligible}" if t3_eligible > 0 else "0 / 0")

st.divider()

# --- 2. DROPDOWN & FILTER LOGIC ---
st.markdown("### Stock Target Details")
options = ["Show All (Target Met)"] + df["Ticker"].tolist()
selected_view = st.selectbox("Filter Stocks by:", options)

if selected_view == "Show All (Target Met)":
    display_df = df[df['T1_Date'].notna()].reset_index(drop=True)
    if display_df.empty:
        st.info("None of the stocks have hit their T1 target yet.")
else:
    display_df = df[df['Ticker'] == selected_view].reset_index(drop=True)

# Helper function to format target strings
def format_target(val, date):
    val_str = f"₹{val}" if pd.notna(val) else "None"
    date_str = f"✅ {date}" if pd.notna(date) else "Pending"
    if pd.isna(val): return "N/A"
    return f"**Target:** {val_str}  |  **Hit On:** {date_str}"

# --- 3. DISPLAY LOGIC ---
if selected_view == "Show All (Target Met)":
    cols = st.columns(2)
    for index, row in display_df.iterrows():
        col_index = index % 2 
        with cols[col_index]:
            with st.container(border=True):
                st.subheader(f"📈 {row['Ticker']}")
                st.markdown(f"**⏱️ Days Tracked:** {row['Days']}")
                st.markdown(f"**T1** - {format_target(row['T1'], row['T1_Date'])}")
                st.markdown(f"**T2** - {format_target(row['T2'], row['T2_Date'])}")
                st.markdown(f"**T3** - {format_target(row['T3'], row['T3_Date'])}")

else:
    row = display_df.iloc[0]
    ticker = row['Ticker']
    
    col_info, col_chart = st.columns([1, 2])
    
    with col_info:
        with st.container(border=True):
            st.subheader(f"📈 {ticker}")
            st.markdown(f"**⏱️ Days Tracked:** {row['Days']}")
            st.markdown(f"**T1** - {format_target(row['T1'], row['T1_Date'])}")
            st.markdown(f"**T2** - {format_target(row['T2'], row['T2_Date'])}")
            st.markdown(f"**T3** - {format_target(row['T3'], row['T3_Date'])}")
            
    with col_chart:
        with st.spinner(f"Fetching live price for {ticker}..."):
            current_price = get_live_price(ticker)
        
        fig = go.Figure()
        y_pos = [0] 

        if pd.notna(row["Stop Loss"]):
            fig.add_trace(go.Scatter(x=[row["Stop Loss"]], y=y_pos, mode='markers+text', 
                                     marker=dict(color='red', size=16, symbol='triangle-down'),
                                     name="Stop Loss", text=[f"SL<br>₹{row['Stop Loss']}"], textposition="bottom center"))
            
        if pd.notna(row["Entry"]):
            fig.add_trace(go.Scatter(x=[row["Entry"]], y=y_pos, mode='markers+text', 
                                     marker=dict(color='gray', size=14, symbol='square'),
                                     name="Entry", text=[f"Entry<br>₹{row['Entry']}"], textposition="top center"))
            
        if pd.notna(row["T1"]):
            fig.add_trace(go.Scatter(x=[row["T1"]], y=y_pos, mode='markers+text', 
                                     marker=dict(color='#2ca02c', size=16, symbol='triangle-up'),
                                     name="T1", text=[f"T1<br>₹{row['T1']}"], textposition="top center"))
            
        if pd.notna(row["T2"]):
            fig.add_trace(go.Scatter(x=[row["T2"]], y=y_pos, mode='markers+text', 
                                     marker=dict(color='#2ca02c', size=16, symbol='triangle-up'),
                                     name="T2", text=[f"T2<br>₹{row['T2']}"], textposition="bottom center"))

        if pd.notna(row["T3"]):
            fig.add_trace(go.Scatter(x=[row["T3"]], y=y_pos, mode='markers+text', 
                                     marker=dict(color='#2ca02c', size=16, symbol='triangle-up'),
                                     name="T3", text=[f"T3<br>₹{row['T3']}"], textposition="top center"))

        if current_price:
            fig.add_trace(go.Scatter(x=[current_price], y=y_pos, mode='markers+text', 
                                     marker=dict(color='blue', size=18, symbol='circle'),
                                     name="Current (Live)", text=[f"Live<br>₹{current_price}"], textposition="top center"))
            st.caption(f"*(Live price fetched from Yahoo Finance: ₹{current_price})*")
        else:
            st.caption("*(Could not fetch live price from Yahoo Finance. Showing static levels only.)*")

        min_x = min([x for x in [row["Stop Loss"], row["Entry"]] if pd.notna(x)] or [0])
        max_x = max([x for x in [row["T1"], row["T2"], row["T3"]] if pd.notna(x)] or [0])
        
        if min_x != 0 and max_x != 0:
            fig.add_shape(type="line", x0=min_x, y0=0, x1=max_x, y1=0, 
                          line=dict(color="lightgray", width=3, dash="dot"), layer="below")

        fig.update_layout(
            title="Setup Anatomy",
            xaxis_title="Price (₹)",
            yaxis=dict(showticklabels=False, zeroline=False), 
            height=300,
            showlegend=False,
            margin=dict(l=20, r=20, t=40, b=20),
            plot_bgcolor='rgba(0,0,0,0)' 
        )
        
        st.plotly_chart(fig, use_container_width=True)
