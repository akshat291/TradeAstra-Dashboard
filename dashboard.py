import streamlit as st
import pandas as pd
import json
import yfinance as yf
import plotly.graph_objects as go
import boto3
from dotenv import load_dotenv
import os
import datetime

# Load environment variables for AWS
load_dotenv()

access_key = os.getenv('aws_access_key_id')
secret_access_key = os.getenv('aws_secret_access_key')

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Target Analysis Dashboard", layout="wide")
st.title("Target Hit Analysis")
st.markdown("Track target achievements and visualize live price action against your trade setup.")

# --- S3 DATA FETCHING ---
@st.cache_data(ttl=600)
def fetch_json_from_s3(bucket_name, object_key):
    try:
        s3 = boto3.client(
            's3', 
            region_name='us-east-1', 
            aws_access_key_id=access_key, 
            aws_secret_access_key=secret_access_key
        )
        response = s3.get_object(Bucket=bucket_name, Key=object_key)
        file_content = response['Body'].read().decode('utf-8')
        return json.loads(file_content)
    except s3.exceptions.NoSuchKey:
        return None 
    except Exception as e:
        st.error(f"Failed to fetch data from S3. Error: {e}")
        st.stop()

# --- HELPER: LIVE PRICE FETCHER ---
@st.cache_data(ttl=300)
def get_live_price(ticker):
    try:
        yf_ticker = f"{ticker}.NS" 
        stock = yf.Ticker(yf_ticker)
        hist = stock.history(period="1d")
        if not hist.empty:
            return round(hist['Close'].iloc[-1], 2)
        return None
    except Exception:
        return None

# --- HELPER: DAILY PRICE FETCHER FOR CHART ---
@st.cache_data(ttl=300)
def get_daily_prices(ticker, period="1mo"):
    try:
        yf_ticker = f"{ticker}.NS"
        stock = yf.Ticker(yf_ticker)
        hist = stock.history(period=period, interval="1d") 
        return hist
    except Exception:
        return pd.DataFrame()

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
        final_validation = details.get("final_validation") or {}
        
        # We ensure all keys exist so filters don't break even if analyst data is sparse
        data.append({
            "Ticker": ticker,
            "Entry": details.get("entry_price"),
            "Stop Loss": details.get("stop_loss"),
            "Last_Close": details.get("last_close"),
            "T1": targets.get("T1"),
            "T2": targets.get("T2"),
            "T3": targets.get("T3"),
            "T1_Date": hit_dates.get("T1"),
            "T2_Date": hit_dates.get("T2"),
            "T3_Date": hit_dates.get("T3"),
            "Publish_Status": final_validation.get("status", "PUBLISH"), # Default to PUBLISH for Analyst tips if not specified
            "Trade_Status": details.get("status", "ACTIVE"),
            "Final_Score": details.get("final_score", 0.0),
            "Category": details.get("category", "Telegram Analyst"),
            "Predicted_5d": details.get("predicted_5d", []),
            "LSTM_Prediction": details.get("lstm_prediction", []),
            "XGBoost_Prediction": details.get("xgboost_prediction", [])
        })
        
    return pd.DataFrame(data)

# ==========================================
# SIDEBAR: DATE & SOURCE SELECTION
# ==========================================
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
current_date = datetime.datetime.now(IST).date() - datetime.timedelta(days=1)
start_date = datetime.date(2026, 4, 24)

default_date = current_date
if default_date.weekday() == 5:  # Saturday
    default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:  # Sunday
    default_date -= datetime.timedelta(days=2)

st.sidebar.header("Configuration")
selected_date = st.sidebar.date_input(
    "1. Select Trading Day:", 
    value=default_date,
    min_value=start_date,
    max_value=current_date,
    format="YYYY-MM-DD"
)

# --- THE TELEGRAM SOURCE TOGGLE ---
data_source = st.sidebar.selectbox(
    "2. Data Source:",
    ["Automated System", "Telegram Tip (Analyst)"],
    help="Switch between pipeline-generated predictions and Finance Analyst tips."
)

if selected_date.weekday() >= 5:
    st.sidebar.error(f"🛑 Market is closed on weekends.")
    st.stop()

# ==========================================
# S3 DYNAMIC ROUTING
# ==========================================
BUCKET_NAME = "swapnil-miscellaneous"
year_str = str(selected_date.year)
month_str = selected_date.strftime('%m')
day_str = selected_date.strftime('%d')

if data_source == "Telegram Tip (Analyst)":
    # Routing to analyst folder
    FILE_KEY = f"telegram_tracker/year={year_str}/month={month_str}/day={day_str}/telegram_tip.json"
else:
    # Routing to system folder
    FILE_KEY = f"target_tracker/year={year_str}/month={month_str}/day={day_str}/target.json"

with st.spinner(f"Fetching {data_source} data for {selected_date}..."):
    parsed_json = fetch_json_from_s3(BUCKET_NAME, FILE_KEY)
    
if parsed_json:
    raw_df = load_data(parsed_json)
else:
    st.warning(f"No {data_source} data found in S3 for {selected_date.strftime('%d %b %Y')}.")
    st.stop()

# --- SIDEBAR: FILTERING LOGIC ---
st.sidebar.divider()
st.sidebar.header("Filter Settings")

filter_mode = st.sidebar.radio(
    "Select Display Mode:",
    ["PUBLISH Status", "Final Score", "Category"]
)

if filter_mode == "PUBLISH Status":
    st.sidebar.info("Showing stocks with status: PUBLISH")
    df = raw_df[raw_df['Publish_Status'] == 'PUBLISH'].copy()

elif filter_mode == "Final Score":
    max_items = len(raw_df)
    top_n = st.sidebar.number_input(
        "Show Top N Stocks", 
        min_value=1, 
        max_value=max_items if max_items > 0 else 1, 
        value=min(10, max_items), 
        step=1
    )
    df = raw_df.nlargest(top_n, 'Final_Score').copy()

elif filter_mode == "Category":
    available_categories = sorted(raw_df['Category'].dropna().unique().tolist())
    category_counts = raw_df['Category'].value_counts().to_dict()
    
    selected_categories = st.sidebar.multiselect(
        "Select Categories", 
        options=available_categories, 
        default=available_categories,
        format_func=lambda x: f"{x} ({category_counts.get(x, 0)})"
    )
    df = raw_df[raw_df['Category'].isin(selected_categories)].copy()

if df.empty:
    st.warning("No stocks match your current filter criteria.")
    st.stop()

# --- 1. KPI CARDS ---
st.markdown(f"### {data_source} Performance Overview")

total_stocks = len(df)
t1_met = len(df[df['T1_Date'].notna()])
t2_eligible = len(df[df['T2'].notna()])
t2_met = len(df[df['T2_Date'].notna()])
t3_eligible = len(df[df['T3'].notna()])
t3_met = len(df[df['T3_Date'].notna()])

kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric("T1 Targets Met", f"{t1_met} / {total_stocks}")
kpi2.metric("T2 Targets Met", f"{t2_met} / {t2_eligible}" if t2_eligible > 0 else "0 / 0")
kpi3.metric("T3 Targets Met", f"{t3_met} / {t3_eligible}" if t3_eligible > 0 else "0 / 0")

st.divider()

# --- 2. DROPDOWN & FILTER LOGIC ---
st.markdown("### Stock Target Details")
options = ["Show All (Target Met)", "Show All (DEAD)"] + df["Ticker"].tolist()
selected_view = st.selectbox("View Specific Stock:", options)

if selected_view == "Show All (Target Met)":
    display_df = df[df['T1_Date'].notna()].reset_index(drop=True)
    if display_df.empty:
        st.info("No stocks have hit T1 yet.")
elif selected_view == "Show All (DEAD)":
    display_df = df[df['Trade_Status'] == 'DEAD'].reset_index(drop=True)
    if display_df.empty:
        st.info("No stocks are currently in DEAD status.")
else:
    display_df = df[df['Ticker'] == selected_view].reset_index(drop=True)

def format_target(val, date):
    val_str = f"₹{val}" if pd.notna(val) else "None"
    date_str = f"✅ {date}" if pd.notna(date) else "Pending"
    if pd.isna(val): return "N/A"
    return f"**Target:** {val_str}  |  **Hit On:** {date_str}"

# --- 3. DISPLAY LOGIC ---
if selected_view in ["Show All (Target Met)", "Show All (DEAD)"] and not display_df.empty:
    cols = st.columns(2)
    for index, row in display_df.iterrows():
        col_index = index % 2 
        with cols[col_index]:
            with st.container(border=True):
                st.subheader(f"📈 {row['Ticker']}")
                st.caption(f"**Score:** {row['Final_Score']} | **Category:** {row['Category']} | **Trade Status:** {row['Trade_Status']}")
                st.markdown(f"**T1** - {format_target(row['T1'], row['T1_Date'])}")
                st.markdown(f"**T2** - {format_target(row['T2'], row['T2_Date'])}")
                st.markdown(f"**T3** - {format_target(row['T3'], row['T3_Date'])}")

elif not display_df.empty:
    row = display_df.iloc[0]
    ticker = row['Ticker']
    
    col_info, col_chart = st.columns([1, 2])
    
    with col_info:
        with st.container(border=True):
            st.subheader(f"📈 {ticker}")
            st.caption(f"**Score:** {row['Final_Score']} | **Category:** {row['Category']} | **Trade Status:** {row['Trade_Status']}")
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

        if current_price:
            fig.add_trace(go.Scatter(x=[current_price], y=y_pos, mode='markers+text', 
                                     marker=dict(color='blue', size=18, symbol='circle'),
                                     name="Current (Live)", text=[f"Live<br>₹{current_price}"], textposition="top center"))
            
        min_vals = [x for x in [row["Stop Loss"], row["Entry"]] if pd.notna(x)]
        max_vals = [x for x in [row["T1"], row["T2"], row["T3"], current_price] if pd.notna(x)]
        
        if min_vals and max_vals:
            fig.add_shape(type="line", x0=min(min_vals), y0=0, x1=max(max_vals), y1=0, 
                          line=dict(color="lightgray", width=3, dash="dot"), layer="below")

        fig.update_layout(
            title="Setup Anatomy",
            xaxis_title="Price (₹)",
            yaxis=dict(showticklabels=False, zeroline=False), 
            height=250,
            showlegend=False,
            margin=dict(l=20, r=20, t=40, b=20),
            plot_bgcolor='rgba(0,0,0,0)' 
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- PREDICTION CHART SECTION ---
    if row['Predicted_5d'] or row.get('LSTM_Prediction') or row.get('XGBoost_Prediction'):
        st.markdown("#### Actual vs Predicted Price (5-Day Horizon)")
        
        with st.spinner("Fetching historical daily data..."):
            hist_df = get_daily_prices(ticker, period="1mo")
            
        fig_line = go.Figure()

        # Actual Price Trace
        if not hist_df.empty:
            hist_df.index = hist_df.index.tz_localize(None).normalize()
            fig_line.add_trace(go.Scatter(
                x=hist_df.index, y=hist_df['Close'], 
                mode='lines+markers', name='Actual Price',
                line=dict(color='blue', width=2), marker=dict(size=6)
            ))
            
        # Base Prediction Trace
        if row['Predicted_5d']:
            p_dates = [pd.to_datetime(item['date']) for item in row['Predicted_5d']]
            p_prices = [item['price'] for item in row['Predicted_5d']]
            fig_line.add_trace(go.Scatter(
                x=p_dates, y=p_prices, mode='lines+markers', name='Base Prediction',
                line=dict(color='orange', width=2, dash='dash'), marker=dict(size=8, symbol='diamond')
            ))
            
        # LSTM Trace
        if row.get('LSTM_Prediction'):
            l_dates = [pd.to_datetime(item['date']) for item in row['LSTM_Prediction']]
            l_prices = [item['price'] for item in row['LSTM_Prediction']]
            fig_line.add_trace(go.Scatter(
                x=l_dates, y=l_prices, mode='lines+markers', name='LSTM Prediction',
                line=dict(color='purple', width=2, dash='dot'), marker=dict(size=8, symbol='square')
            ))
            
        # XGBoost Trace
        if row.get('XGBoost_Prediction'):
            x_dates = [pd.to_datetime(item['date']) for item in row['XGBoost_Prediction']]
            x_prices = [item['price'] for item in row['XGBoost_Prediction']]
            fig_line.add_trace(go.Scatter(
                x=x_dates, y=x_prices, mode='lines+markers', name='XGBoost Prediction',
                line=dict(color='green', width=2, dash='dashdot'), marker=dict(size=8, symbol='triangle-up')
            ))

        # SL Horizontal Line
        if pd.notna(row["Stop Loss"]):
            fig_line.add_hline(y=row["Stop Loss"], line_dash="dot", line_color="red", 
                               annotation_text="Stop Loss", annotation_position="bottom right")

        fig_line.update_layout(
            yaxis_title="Price (₹)", height=400,
            margin=dict(l=20, r=20, t=20, b=20),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig_line, use_container_width=True)
