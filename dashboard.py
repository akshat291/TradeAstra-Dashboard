import streamlit as st
import pandas as pd
import json
import yfinance as yf
import plotly.graph_objects as go
import boto3
from dotenv import load_dotenv
import os
import datetime

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
        s3 = boto3.client('s3', region_name='us-east-1', aws_access_key_id=access_key, aws_secret_access_key=secret_access_key)
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
    except Exception as e:
        return None

# --- HELPER: DAILY PRICE FETCHER FOR CHART ---
@st.cache_data(ttl=300)
def get_daily_prices(ticker, period="1mo"):
    try:
        yf_ticker = f"{ticker}.NS"
        stock = yf.Ticker(yf_ticker)
        hist = stock.history(period=period, interval="1d") 
        return hist
    except Exception as e:
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
            # SEPARATED THE TWO STATUSES HERE:
            "Publish_Status": final_validation.get("status", "UNKNOWN"),
            "Trade_Status": details.get("status", "UNKNOWN"),
            "Final_Score": details.get("final_score", 0.0),
            "Category": details.get("category", "UNKNOWN"),
            "Predicted_5d": details.get("predicted_5d", [])
        })
        
    return pd.DataFrame(data)

# ==========================================
# DATE SELECTION LOGIC (Calendar UI)
# ==========================================
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
current_date = datetime.datetime.now(IST).date()
start_date = datetime.date(2026, 4, 24)

default_date = current_date
if default_date.weekday() == 5:  # Saturday
    default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:  # Sunday
    default_date -= datetime.timedelta(days=2)

st.sidebar.header("Select Trading Day")
selected_date = st.sidebar.date_input(
    "Choose a date to track:", 
    value=default_date,
    min_value=start_date,
    max_value=current_date,
    format="YYYY-MM-DD"
)

if selected_date.weekday() >= 5:
    day_name = selected_date.strftime('%A')
    st.sidebar.error(f"🛑 {day_name}s are not trading days. Please select a valid weekday.")
    st.warning("The market is closed on weekends. No data is generated.")
    st.stop()


# ==========================================
# MAIN APP EXECUTION
# ==========================================
BUCKET_NAME = "swapnil-miscellaneous"
FILE_KEY = f"target_tracker/year={selected_date.year}/month={selected_date.strftime('%m')}/day={selected_date.strftime('%d')}/target.json"

with st.spinner(f"Fetching S3 data for {selected_date.strftime('%Y-%m-%d')}..."):
    parsed_json = fetch_json_from_s3(BUCKET_NAME, FILE_KEY)
    
if parsed_json:
    raw_df = load_data(parsed_json)
else:
    st.warning(f"No target tracking data found in S3 for {selected_date.strftime('%d %b %Y')}. It may not have been processed yet.")
    st.stop()


# --- SIDEBAR: FILTERING LOGIC ---
st.sidebar.divider()
st.sidebar.header("Filter Settings")

filter_mode = st.sidebar.radio(
    "Select Display Mode:",
    ["PUBLISH Status", "Final Score", "Category"]
)

if filter_mode == "PUBLISH Status":
    st.sidebar.info("Currently showing stocks with status: PUBLISH")
    # Updated to filter by Publish_Status
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
options = ["Show All (Target Met)", "Show All (DEAD)"] + df["Ticker"].tolist()
selected_view = st.selectbox("View Specific Stock:", options)

if selected_view == "Show All (Target Met)":
    display_df = df[df['T1_Date'].notna()].reset_index(drop=True)
    if display_df.empty:
        st.info("None of the filtered stocks have hit their T1 target yet.")
elif selected_view == "Show All (DEAD)":
    # Updated to correctly filter by Trade_Status
    display_df = df[df['Trade_Status'] == 'DEAD'].reset_index(drop=True)
    if display_df.empty:
        st.info("None of the filtered stocks currently have a DEAD status.")
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
                # Updated to show Trade_Status
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
            # Updated to show Trade_Status
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
            
        min_x = min([x for x in [row["Stop Loss"], row["Entry"]] if pd.notna(x)] or [0])
        max_x = max([x for x in [row["T1"], row["T2"], row["T3"]] if pd.notna(x)] or [0])
        
        if min_x != 0 and max_x != 0:
            fig.add_shape(type="line", x0=min_x, y0=0, x1=max_x, y1=0, 
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

    if row['Predicted_5d']:
        st.markdown("#### Actual vs Predicted Price (5-Day Horizon)")
        
        pred_dates = [pd.to_datetime(item['date']) for item in row['Predicted_5d']]
        pred_prices = [item['price'] for item in row['Predicted_5d']]
        
        with st.spinner("Fetching historical daily data..."):
            hist_df = get_daily_prices(ticker, period="1mo")
            
        fig_line = go.Figure()

        if not hist_df.empty and len(pred_dates) > 0:
            hist_df.index = hist_df.index.tz_localize(None).normalize()
            start_dt = pred_dates[0]
            end_dt = pred_dates[-1]
            
            filtered_hist = hist_df[(hist_df.index >= start_dt) & (hist_df.index <= end_dt)]
            
            if not filtered_hist.empty:
                fig_line.add_trace(go.Scatter(
                    x=filtered_hist.index, 
                    y=filtered_hist['Close'], 
                    mode='lines+markers', 
                    name='Actual Price (Daily Close)',
                    line=dict(color='blue', width=2),
                    marker=dict(size=8, color='blue')
                ))
            
        fig_line.add_trace(go.Scatter(
            x=pred_dates, 
            y=pred_prices, 
            mode='lines+markers', 
            name='Predicted Price',
            line=dict(color='orange', width=2, dash='dash'),
            marker=dict(size=8, symbol='diamond', color='orange')
        ))

        if pd.notna(row["Stop Loss"]):
            fig_line.add_hline(
                y=row["Stop Loss"], 
                line_dash="dot", 
                line_color="red", 
                line_width=2,
                annotation_text=f"Stop Loss (₹{row['Stop Loss']})", 
                annotation_position="bottom right",
                annotation_font_color="red"
            )

        if pd.notna(row["Last_Close"]):
            fig_line.add_hline(
                y=row["Last_Close"], 
                line_dash="dot", 
                line_color="gray", 
                line_width=2,
                annotation_text=f"Last Close (₹{row['Last_Close']})", 
                annotation_position="top left",
                annotation_font_color="gray"
            )

        if len(pred_dates) > 0:
            padding = pd.Timedelta(hours=12)
            fig_line.update_xaxes(
                range=[pred_dates[0] - padding, pred_dates[-1] + padding],
                title="Date",
                tickformat="%d %b"
            )

        fig_line.update_layout(
            yaxis_title="Price (₹)",
            height=400,
            margin=dict(l=20, r=20, t=20, b=20),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        st.plotly_chart(fig_line, use_container_width=True)
