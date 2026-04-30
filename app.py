import streamlit as st
import pandas as pd
import requests
from icalendar import Calendar
from datetime import datetime, date, timedelta
from supabase import create_client, Client
from streamlit_calendar import calendar
import smtplib
from email.mime.text import MIMEText

# --- APP LAYOUT & THEME OVERRIDE ---
st.set_page_config(page_title="Meter2 Properties Command Center", layout="wide", initial_sidebar_state="expanded")

# --- CUSTOM CSS FOR MOCKUP STYLING ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;700&display=swap');
html, body, [class*="css"]  {
    font-family: 'Roboto', sans-serif;
}
.stApp {
    background-color: #F4F4F4;
    color: #333333;
}
.fc-header-toolbar {
    background-color: #F65C78 !important; 
    color: white !important;
    padding: 15px !important;
    border-radius: 5px 5px 0 0 !important;
    margin-bottom: 0 !important;
}
.fc-toolbar-title {
    font-weight: 300 !important;
    font-size: 1.5rem !important;
}
.fc-button-primary {
    background-color: transparent !important;
    border-color: white !important;
    box-shadow: none !important;
}
.fc-button-primary:hover {
    background-color: rgba(255,255,255,0.2) !important;
}
.fc-view-harness {
    background-color: white !important;
    border-radius: 0 0 5px 5px !important;
    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
}
.event-card {
    background-color: white;
    padding: 15px;
    border-radius: 5px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    margin-bottom: 15px;
    border-left: 4px solid;
}
</style>
""", unsafe_allow_html=True)

# --- SETUP SUPABASE CONNECTION ---
@st.cache_resource
def init_connection() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# --- CUSTOMIZATION ---
COMPANY_NAME = "Meter2 Properties"
PROP_SWAKOP = "Starshine Guesthouse (Swakopmund)"
PROP_PLETT = "Melkweg Farmhouse (Plettenberg)"
PROPERTIES = [PROP_SWAKOP, PROP_PLETT]

# --- RECIPIENT EMAILS ---
NOTIFICATION_EMAILS = [
    "menradholm2@gmail.com"
]

# --- AIRBNB ICAL LINKS ---
URL_SWAKOP = "https://www.airbnb.at/calendar/ical/1269982642892159382.ics?t=1d2c8992d5a847febc8bfa4d68c4dc1d"
URL_PLETT_FULL = "https://www.airbnb.at/calendar/ical/1327289595267027214.ics?t=2fc0352915bf4d0aba96926db8f51aab"
URL_PLETT_LESS = "https://www.airbnb.at/calendar/ical/1525842544711145278.ics?t=7e30a8982d984a0cb483dcd06a3276ca"

# --- EMAIL NOTIFICATION FUNCTION ---
def send_email_notification(subject, message_body):
    try:
        sender = st.secrets["EMAIL_SENDER"]
        password = st.secrets["EMAIL_PASSWORD"]
        
        msg = MIMEText(message_body)
        msg['Subject'] = subject
        msg['From'] = sender
        # Join the list of emails into a single comma-separated string
        msg['To'] = ", ".join(NOTIFICATION_EMAILS)

        # Connect to Gmail's server
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, password)
            server.send_message(msg)
    except Exception as e:
        st.error(f"Email failed to send. Please check your Secrets configuration. Error: {e}")

# --- 1. CLOUD DATABASE FUNCTIONS ---
def add_internal_booking(property_name, guest_name, start_date, end_date):
    data = {
        "property_name": property_name,
        "guest_name": guest_name,
        "start_date": start_date,
        "end_date": end_date,
        "status": "PENDING"
    }
    supabase.table("internal_bookings").insert(data) # No .execute()

def update_status(booking_id, new_status):
    supabase.table("internal_bookings").update({"status": new_status}).eq("id", booking_id) # No .execute()

def get_internal_bookings(property_name=None, status=None):
    query = supabase.table("internal_bookings").select("*")
    if property_name:
        query = query.eq("property_name", property_name)
    if status:
        query = query.eq("status", status)
        
    response = query.execute()
    
    if response.data:
        return pd.DataFrame(response.data)
    else:
        return pd.DataFrame(columns=['id', 'property_name', 'guest_name', 'start_date', 'end_date', 'status'])

# --- 2. FETCH AIRBNB CALENDARS ---
def fetch_airbnb_events(url, property_name, sub_label=""):
    events = []
    try:
        response = requests.get(url)
        response.raise_for_status()
        cal = Calendar.from_ical(response.content)
        
        for component in cal.walk('vevent'):
            start = component.get('dtstart').dt
            end = component.get('dtend').dt
            
            if isinstance(start, datetime): start = start.date()
            if isinstance(end, datetime): end = end.date()
            
            guest_label = "AirBnB Booking"
            if sub_label:
                guest_label += f" ({sub_label})"
                
            events.append({
                'property_name': property_name,
                'guest_name': guest_label,
                'start_date': str(start),
                'end_date': str(end),
                'status': 'AIRBNB_CONFIRMED'
            })
    except Exception as e:
        st.error(f"Could not sync calendar for {property_name}: {e}")
    return events

@st.cache_data(ttl=300)
def get_all_airbnb_bookings():
    swakop = fetch_airbnb_events(URL_SWAKOP, PROP_SWAKOP)
    plett_full = fetch_airbnb_events(URL_PLETT_FULL, PROP_PLETT, "Full Capacity")
    plett_less = fetch_airbnb_events(URL_PLETT_LESS, PROP_PLETT, "Reduced Capacity")
    
    all_events = swakop + plett_full + plett_less
    if all_events:
        return pd.DataFrame(all_events)
    return pd.DataFrame(columns=['property_name', 'guest_name', 'start_date', 'end_date', 'status'])

# --- 3. MONTH CALENDAR VIEW ---
def draw_month_calendar(df):
    if df.empty:
        st.info("No events to display.")
        return

    color_map = {
        "AIRBNB_CONFIRMED": "#E34C51", 
        "APPROVED": "#1DB9A3",         
        "PENDING": "#F5A623",          
        "REJECTED": "#555555"          
    }

    calendar_events = []
    for _, row in df.iterrows():
        end_date_obj = pd.to_datetime(row['end_date']) + timedelta(days=1)
        
        calendar_events.append({
            "title": f"{row['guest_name']} ({row['property_name'][:10]}...)",
            "start": row['start_date'],
            "end": end_date_obj.strftime('%Y-%m-%d'),
            "backgroundColor": color_map.get(row['status'], "#3788d8"),
            "borderColor": color_map.get(row['status'], "#3788d8"),
        })

    calendar_options = {
        "headerToolbar": {
            "left": "prev",
            "center": "title",
            "right": "next"
        },
        "initialView": "dayGridMonth",
        "height": 650,
        "selectable": False,       # Stops users from highlighting blank dates
        "editable": False,         # Stops users from trying to drag-and-drop bookings
        "eventStartEditable": False,
        "eventDurationEditable": False
    }

    cal_col, list_col = st.columns([2.5, 1])

    with cal_col:
        calendar(events=calendar_events, options=calendar_options)

    with list_col:
        st.markdown("<h4 style='color: #666; font-weight: 400;'>Upcoming Check-Ins</h4>", unsafe_allow_html=True)
        
        df['start_date'] = pd.to_datetime(df['start_date'])
        future_events = df[df['start_date'] >= pd.Timestamp.today()].sort_values('start_date').head(5)
        
        for _, row in future_events.iterrows():
            border_color = color_map.get(row['status'], '#ccc')
            formatted_date = row['start_date'].strftime('%B %d, %Y')
            
            card_html = f"""
            <div class="event-card" style="border-left-color: {border_color};">
                <div style="font-size: 0.8em; color: {border_color}; font-weight: bold; text-transform: uppercase;">{row['status']}</div>
                <div style="font-weight: bold; font-size: 1.1em; margin: 5px 0;">{row['guest_name']}</div>
                <div style="font-size: 0.9em; color: #666;">{row['property_name']}</div>
                <div style="font-size: 0.8em; color: #999; margin-top: 5px;">📅 {formatted_date}</div>
            </div>
            """
            st.markdown(card_html, unsafe_allow_html=True)

# --- 4. APP LAYOUT & LOGIC ---
st.sidebar.title(f"🌍 {COMPANY_NAME}")
role = st.sidebar.radio("Switch View:", [
    "Manager (Team View)", 
    f"Owner - {PROP_SWAKOP}", 
    f"Owner - {PROP_PLETT}"
])

if role == "Manager (Team View)":
    st.title("Event Calendar Dashboard")
    
    with st.expander("➕ Add New Internal Booking Request"):
        with st.form("new_request"):
            col1, col2, col3, col4 = st.columns(4)
            with col1: prop = st.selectbox("Property", PROPERTIES)
            with col2: guest = st.text_input("Guest Name")
            with col3: start = st.date_input("Check-In")
            with col4: end = st.date_input("Check-Out")
            submit = st.form_submit_button("Submit Request")
            
            if submit:
                # 1. Save to Database
                add_internal_booking(prop, guest, str(start), str(end))
                
                # 2. Format & Send Email
                subject = f"🔔 Action Required: New Booking Request for {prop}"
                body = f"""Hello Team,

A new internal booking request has been submitted and is waiting for owner approval.

Property: {prop}
Guest: {guest}
Dates: {start} to {end}

Please check the Meter2 Command Center dashboard to approve or reject this request.

- Automated Notification System
"""
                send_email_notification(subject, body)
                
                st.success(f"Request saved! Notification emails sent to the team.")
                st.rerun()
                
    internal_df = get_internal_bookings()
    airbnb_df = get_all_airbnb_bookings()
    
    master_df = pd.concat([internal_df, airbnb_df], ignore_index=True) if not (internal_df.empty and airbnb_df.empty) else pd.DataFrame()
    
    if not master_df.empty:
        draw_month_calendar(master_df)
    else:
        st.info("No bookings found in database or AirBnB.")

else:
    prop_name = role.split("Owner - ")[1]
    st.title(f"{prop_name} Calendar")
    
    df_pending = get_internal_bookings(property_name=prop_name, status='PENDING')
    if not df_pending.empty:
        st.warning("🔔 Action Required: Pending Approvals")
        for index, row in df_pending.iterrows():
            col_text, col_btn1, col_btn2 = st.columns([3, 1, 1])
            col_text.write(f"**{row['guest_name']}** ({row['start_date']} to {row['end_date']})")
            
            if col_btn1.button("✅ Approve", key=f"app_{row['id']}"):
                update_status(row['id'], 'APPROVED')
                
                # Send Approval Email
                subject = f"✅ Booking APPROVED: {row['guest_name']} at {prop_name}"
                body = f"The pending booking for {row['guest_name']} from {row['start_date']} to {row['end_date']} at {prop_name} has been officially APPROVED by the owner."
                send_email_notification(subject, body)
                
                st.rerun()
                
            if col_btn2.button("❌ Reject", key=f"rej_{row['id']}"):
                update_status(row['id'], 'REJECTED')
                
                # Send Rejection Email
                subject = f"❌ Booking REJECTED: {row['guest_name']} at {prop_name}"
                body = f"The pending booking for {row['guest_name']} from {row['start_date']} to {row['end_date']} at {prop_name} was REJECTED."
                send_email_notification(subject, body)
                
                st.rerun()
        st.markdown("---")
        
    airbnb_df = get_all_airbnb_bookings()
    internal_df = get_internal_bookings(property_name=prop_name)
    
    if not airbnb_df.empty:
        airbnb_df = airbnb_df[airbnb_df['property_name'] == prop_name]
    if not internal_df.empty:
        internal_df = internal_df[internal_df['status'] == 'APPROVED']
        
    owner_master_df = pd.concat([internal_df, airbnb_df], ignore_index=True) if not (internal_df.empty and airbnb_df.empty) else pd.DataFrame()
    
    if not owner_master_df.empty:
        draw_month_calendar(owner_master_df)
    else:
        st.info("No confirmed bookings yet.")