"""ShiftGuard Admin Dashboard.

A Streamlit-based dashboard for managing employee schedules,
viewing availability, and publishing shifts to Google Calendar.

Usage:
    cd dashboard
    pip install -r requirements.txt
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from datetime import date, timedelta, datetime
import time

# Page configuration
st.set_page_config(
    page_title="ShiftGuard Admin",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for styling
st.markdown("""
<style>
    .stDataFrame {
        font-size: 14px;
    }
    .violation-row {
        background-color: #ffcccc !important;
    }
    .published-row {
        background-color: #ccffcc !important;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar Configuration
st.sidebar.title("ShiftGuard Admin")
st.sidebar.markdown("---")

# API Configuration - read from secrets with fallback to sidebar inputs
# Try to get values from st.secrets first (for Streamlit Cloud deployment)
try:
    default_api_url = st.secrets["api"]["url"]
    default_cron_secret = st.secrets["api"]["cron_secret"]
    secrets_configured = True
except (KeyError, FileNotFoundError):
    default_api_url = "https://shiftguard-api.vercel.app"
    default_cron_secret = ""
    secrets_configured = False

if secrets_configured:
    # Use secrets directly - no need to show config UI
    api_url = default_api_url
    cron_secret = default_cron_secret
else:
    # Show manual input for local development
    st.sidebar.subheader("API Configuration")
    api_url = st.sidebar.text_input(
        "API URL",
        value=default_api_url,
        help="Base URL of the ShiftGuard API"
    )
    cron_secret = st.sidebar.text_input(
        "Cron Secret",
        type="password",
        help="Secret for authenticated API calls (schedule generation)"
    )
    st.sidebar.markdown("---")

st.sidebar.markdown("**Status:**")


# Helper function to make API calls
def api_get(endpoint: str, params: dict = None) -> dict:
    """Make a GET request to the API."""
    try:
        url = f"{api_url}{endpoint}"
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API Error: {e}")
        return None


def api_post(endpoint: str, json_data: dict = None, auth: bool = False) -> dict:
    """Make a POST request to the API."""
    try:
        url = f"{api_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if auth and cron_secret:
            headers["Authorization"] = f"Bearer {cron_secret}"
        response = requests.post(url, json=json_data, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API Error: {e}")
        return None


# Check API health
try:
    health = api_get("/api/v1/health")
    if health and health.get("status") == "healthy":
        st.sidebar.success("API Connected")
    else:
        st.sidebar.warning("API Unhealthy")
except Exception:
    st.sidebar.error("API Offline")


# Main content
st.title("ShiftGuard Admin Dashboard")

# Create tabs
tab1, tab2 = st.tabs(["Schedule", "Employee Roster"])

# ====================
# TAB 1: SCHEDULE
# ====================
with tab1:
    st.header("Weekly Schedule")

    # Date picker row
    col1, col2, col3 = st.columns([2, 2, 4])

    # Default to next week (Monday-Sunday)
    today = date.today()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = today + timedelta(days=days_until_monday)
    next_sunday = next_monday + timedelta(days=6)

    with col1:
        start_date = st.date_input("Start Date", value=next_monday)

    with col2:
        end_date = st.date_input("End Date", value=next_sunday)

    with col3:
        status_filter = st.selectbox(
            "Status Filter",
            options=["All", "DRAFT", "AWAITING_RESPONSE", "CONFIRMED", "DECLINED", "PUBLISHED"],
            index=0
        )

    # Fetch and display shifts
    st.markdown("---")

    # Action buttons row
    action_col1, action_col2, action_col3 = st.columns([2, 2, 4])

    with action_col1:
        if st.button("Generate Schedule", type="primary", use_container_width=True):
            with st.spinner("Generating schedule..."):
                result = api_post(
                    "/api/v1/schedule/generate",
                    json_data={
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat()
                    },
                    auth=True
                )
                if result:
                    st.success(f"Generated {result.get('shifts_created', 0)} shifts!")
                    if result.get('violations_flagged', 0) > 0:
                        st.warning(f"{result.get('violations_flagged')} violations flagged")
                    st.rerun()

    with action_col2:
        if st.button("Publish All Shifts", type="secondary", use_container_width=True):
            progress_bar = st.progress(0)
            status_text = st.empty()

            total_published = 0
            total_failed = 0
            batch_num = 0

            while True:
                batch_num += 1
                status_text.text(f"Publishing batch {batch_num}...")

                result = api_post(
                    "/api/v1/schedule/publish",
                    json_data={"batch_size": 5}
                )

                if result is None:
                    st.error("Publish failed")
                    break

                published = result.get("published", 0)
                failed = result.get("failed", 0)
                remaining = result.get("remaining", 0)

                total_published += published
                total_failed += failed

                # Calculate progress
                if remaining == 0 and published == 0:
                    progress_bar.progress(100)
                    break
                elif remaining > 0:
                    total = total_published + remaining
                    progress = int((total_published / total) * 100)
                    progress_bar.progress(min(progress, 99))
                else:
                    progress_bar.progress(100)
                    break

                time.sleep(0.5)  # Small delay between batches

            status_text.text(f"Complete! Published: {total_published}, Failed: {total_failed}")
            if total_published > 0:
                st.success(f"Successfully published {total_published} shifts!")
            st.rerun()

    # Fetch shifts data
    params = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    }
    if status_filter != "All":
        params["status"] = status_filter

    shifts_data = api_get("/api/v1/shifts", params=params)

    if shifts_data and shifts_data.get("shifts"):
        shifts = shifts_data["shifts"]

        # Display metrics
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

        with metric_col1:
            st.metric("Total Shifts", len(shifts))

        with metric_col2:
            violations = sum(1 for s in shifts if s.get("is_violation"))
            st.metric("Violations", violations, delta=None if violations == 0 else f"-{violations}", delta_color="inverse")

        with metric_col3:
            awaiting = sum(1 for s in shifts if s.get("status") == "AWAITING_RESPONSE")
            st.metric("Awaiting Response", awaiting)

        with metric_col4:
            confirmed = sum(1 for s in shifts if s.get("status") == "CONFIRMED")
            st.metric("Confirmed", confirmed)

        st.markdown("---")

        # Convert to DataFrame
        df = pd.DataFrame(shifts)

        # Data Preprocessing
        df["start_time"] = pd.to_datetime(df["start_time"])
        df["end_time"] = pd.to_datetime(df["end_time"])
        df["shift_date"] = df["start_time"].dt.date

        # Determine shift type based on start hour
        def get_shift_type(row):
            hour = row["start_time"].hour if pd.notna(row.get("start_time")) else 0
            if hour == 6:
                return "OPEN"
            elif hour == 10:
                return "MID"
            elif hour == 14:
                return "CLOSE"
            return "OTHER"

        df["shift_type"] = df.apply(get_shift_type, axis=1)

        # Day Selector
        unique_dates = sorted(df["shift_date"].unique())
        date_options = [d.strftime("%A, %b %d") for d in unique_dates]
        date_map = dict(zip(date_options, unique_dates))

        selected_date_label = st.selectbox(
            "Select Day to Visualize",
            options=date_options,
            index=0
        )
        selected_date = date_map[selected_date_label]

        # Filter for selected day
        daily_df = df[df["shift_date"] == selected_date].copy()

        if not daily_df.empty:
            # Shift type color map
            color_map = {
                "OPEN": "#3498db",   # Blue
                "MID": "#f1c40f",    # Gold
                "CLOSE": "#e74c3c", # Red
                "OTHER": "#95a5a6"  # Gray
            }

            # Create Gantt chart
            fig = px.timeline(
                daily_df,
                x_start="start_time",
                x_end="end_time",
                y="employee_name",
                color="shift_type",
                text="shift_type",
                color_discrete_map=color_map,
                labels={"employee_name": "Employee", "shift_type": "Shift Type"}
            )

            # Chart styling
            fig.update_traces(textposition="inside", insidetextanchor="middle")

            # Fixed x-axis range: 5 AM to 11 PM on selected date
            x_min = datetime.combine(selected_date, datetime.strptime("05:00", "%H:%M").time())
            x_max = datetime.combine(selected_date, datetime.strptime("23:00", "%H:%M").time())

            fig.update_layout(
                title=f"Schedule for {selected_date_label}",
                xaxis_title="Time",
                yaxis_title="Employee",
                xaxis=dict(
                    range=[x_min, x_max],
                    tickformat="%I %p",  # "6 AM" format
                    dtick=3600000,       # 1 hour in milliseconds
                    showgrid=True,
                    gridcolor="rgba(128,128,128,0.3)"
                ),
                yaxis=dict(
                    showgrid=True,
                    gridcolor="rgba(128,128,128,0.2)",
                    categoryorder="category ascending"
                ),
                height=600,
                showlegend=True,
                legend_title="Shift Type"
            )

            # Render the chart
            st.plotly_chart(fig, use_container_width=True)

            # Violations table below chart
            violations_df = daily_df[daily_df["is_violation"] == True]
            if not violations_df.empty:
                st.subheader("⚠️ Violations")
                violations_display = violations_df[[
                    "employee_name", "shift_type", "violation_reason"
                ]].copy()
                violations_display.columns = ["Employee", "Shift", "Reason"]
                st.dataframe(violations_display, use_container_width=True, hide_index=True)
        else:
            st.info(f"No shifts scheduled for {selected_date_label}.")

    else:
        st.info("No shifts found for the selected date range. Click 'Generate Schedule' to create shifts.")


# ====================
# TAB 2: EMPLOYEE ROSTER
# ====================
with tab2:
    st.header("Employee Roster")

    if st.button("Refresh Employees", use_container_width=False):
        st.rerun()

    employees_data = api_get("/api/v1/employees")

    if employees_data and employees_data.get("employees"):
        employees = employees_data["employees"]

        st.metric("Total Employees", len(employees))
        st.markdown("---")

        # Display each employee
        for emp in employees:
            with st.expander(f"**{emp['full_name']}** - {emp['email']}", expanded=False):
                col1, col2 = st.columns([1, 3])

                with col1:
                    st.markdown(f"**Max Weekly Hours:** {emp.get('max_weekly_hours', 'N/A')}")
                    st.markdown(f"**Active:** {'Yes' if emp.get('is_active') else 'No'}")

                with col2:
                    st.markdown("**Weekly Availability:**")

                    availability = emp.get("availability", {})

                    if availability:
                        # Create availability table
                        avail_data = []
                        days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

                        for day in days_order:
                            day_avail = availability.get(day, {})
                            can_open = day_avail.get("can_open", False)
                            can_close = day_avail.get("can_close", False)

                            # Determine role
                            if can_open and can_close:
                                role = "Flexible"
                            elif can_open and not can_close:
                                role = "Open Only"
                            elif not can_open and can_close:
                                role = "Close Only"
                            elif not can_open and not can_close:
                                role = "Mid Only"
                            else:
                                role = "Not Available"

                            avail_data.append({
                                "Day": day[:3],
                                "Open": "Yes" if can_open else "No",
                                "Close": "Yes" if can_close else "No",
                                "Role": role
                            })

                        avail_df = pd.DataFrame(avail_data)
                        st.dataframe(avail_df, use_container_width=True, hide_index=True)
                    else:
                        st.warning("No availability data")

        # Summary table
        st.markdown("---")
        st.subheader("Quick Summary")

        summary_data = []
        for emp in employees:
            availability = emp.get("availability", {})

            # Count available days
            open_days = sum(1 for d in availability.values() if d.get("can_open"))
            close_days = sum(1 for d in availability.values() if d.get("can_close"))

            # Determine primary role
            total_open = sum(1 for d in availability.values() if d.get("can_open") and not d.get("can_close"))
            total_close = sum(1 for d in availability.values() if d.get("can_close") and not d.get("can_open"))
            total_mid = sum(1 for d in availability.values() if not d.get("can_open") and not d.get("can_close"))
            total_flex = sum(1 for d in availability.values() if d.get("can_open") and d.get("can_close"))

            if total_flex > max(total_open, total_close, total_mid):
                role = "Flexible"
            elif total_open > max(total_close, total_mid):
                role = "Opener"
            elif total_close > max(total_open, total_mid):
                role = "Closer"
            elif total_mid > 0:
                role = "Mid-Shift"
            else:
                role = "Unknown"

            summary_data.append({
                "Name": emp["full_name"],
                "Email": emp["email"],
                "Role": role,
                "Max Hours": emp.get("max_weekly_hours", "N/A"),
                "Open Days": open_days,
                "Close Days": close_days,
            })

        summary_df = pd.DataFrame(summary_data)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

    else:
        st.info("No employees found. Check API connection.")


# Footer
st.markdown("---")
st.caption("ShiftGuard Admin Dashboard v1.0 | Compliant scheduling for Canadian businesses")
