#Testing
from datetime import datetime
import time
import streamlit as st
import requests
import pandas as pd
from supabase import create_client, Client
from streamlit_calendar import calendar
import plotly.express as px
import re
import smtplib
import random
from email.message import EmailMessage
import streamlit.components.v1 as components


st.set_page_config(page_title="Instagram Manager", layout="wide")

# ✅ Always initialize session state variables
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user_data" not in st.session_state:
    st.session_state.user_data = {}

if "page" not in st.session_state:
    st.session_state.page = "Login"

# Use secrets from Streamlit Cloud
SUPABASE_URL = "https://rorltqhtdwvylyqpillg.supabase.co"
SUPABASE_KEY ="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJvcmx0cWh0ZHd2eWx5cXBpbGxnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTE5NjQxOTYsImV4cCI6MjA2NzU0MDE5Nn0.BeoonWsAXWwzZsnl3zcSVwAKOh5YKYAPvI2XHXW4Its"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_key(key_name):
    res = supabase.table("user_info").select(key_name).eq(key_name, key_name).execute()
    return res.data[0]["key_value"] if res.data else None

#______________________________________________________________________________________________________#
# Get user-specific keys from session state
user_data = st.session_state.get("user_data") or {}
ACCESS_TOKEN = user_data.get("inst_access_token")
IG_USER_ID = user_data.get("ig_user_id")
API_VERSION = st.secrets["API_VERSION"]
GRAPH_URL = "https://graph.facebook.com/v23.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}/{IG_USER_ID}/insights"
#______________________________________________________________________________________________________#

#______________________________________________________________________________________________________#
#Database codes

def update_posting_configs(user_name, num_of_posts, frequency, dont_use_until, posting_hours):
    try:
        response = supabase.table("user_info") \
            .update({
                "num_of_posts": str(num_of_posts),
                "frequency": frequency,
                "dontuseuntil": str(dont_use_until),
                "posting_hours": posting_hours
            }) \
            .eq("user_name", user_name) \
            .execute()
        # If no row was updated, insert a new one
        if not response.data:
            supabase.table("user_info").insert({
                "user_name": user_name,
                "num_of_posts": str(num_of_posts),
                "frequency": frequency,
                "dontuseuntil": str(dont_use_until),
                "posting_hours": posting_hours
            }).execute()
    except Exception as e:
        print(f"❌ Error updating configs for '{user_name}': {e}")

def fetch_posting_configs(user_name):
    try:
        response = supabase.table("user_info") \
            .select("num_of_posts, frequency, dontuseuntil, posting_hours") \
            .eq("user_name", user_name) \
            .execute()
        if not response.data:
            return 1, "Daily", 0  # Default values
        row = response.data[0]
        num_of_posts = row.get("num_of_posts", 1)
        frequency = row.get("frequency", "Daily")
        dontuseuntil = row.get("dontuseuntil", 0)
        posting_hours = row.get("posting_hours")

        # Ensure None is replaced by default
        num_of_posts = int(num_of_posts) if num_of_posts is not None else 1
        dontuseuntil = int(dontuseuntil) if dontuseuntil is not None else 0
        return num_of_posts, frequency, dontuseuntil, posting_hours
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1, "Daily", 0, "11:00, 15:00"

# Update a specific column in a user's post
def update_post(post_id, colname, value, user_name):
    response = supabase.table("posts_db_all") \
        .update({colname: str(value)}) \
        .eq("id", post_id) \
        .eq("user_name", user_name) \
        .execute()
    return response

# Retrieve all posts for a user, ordered by scheduled time
def get_all_posts(user_name):
    response = supabase.table("posts_db_all") \
        .select("*") \
        .eq("user_name", user_name) \
        .order("scheduled_time", desc=False) \
        .execute()
    return response.data if response.data else []

# Delete a user's specific post
def delete_post(post_id, user_name):
    supabase.table("posts_db_all") \
        .delete() \
        .eq("id", post_id) \
        .eq("user_name", user_name) \
        .execute()

#______________________________________________________________________________________________________#

METRICS = [
    "views", "reach", "likes", "comments", "shares",
    "saves", "replies", "accounts_engaged", "total_interactions"
]

# Metrics that support time_series
TIME_SERIES_SUPPORTED = ["reach"]

# Fetch total_value (default)
def fetch_total_value(metric):
    params = {
        "metric": metric,
        "period": "day",
        "metric_type": "total_value",
        "access_token": ACCESS_TOKEN
    }
    r = requests.get(BASE_URL, params=params)
    return r.json()

# Fetch time_series (only for reach)
def fetch_time_series(metric):
    params = {
        "metric": metric,
        "period": "day",
        "metric_type": "time_series",
        "access_token": ACCESS_TOKEN
    }
    r = requests.get(BASE_URL, params=params)
    return r.json()

# Process total or time-series data
def get_metric_data(metric):
    if metric in TIME_SERIES_SUPPORTED:
        res = fetch_time_series(metric)
        if "error" in res or not res.get("data"):
            return None, None, res.get("error", {}).get("message", "No data")
        values = res["data"][0].get("values", [])
        df = pd.DataFrame(values)
        df["end_time"] = pd.to_datetime(df["end_time"])
        df.rename(columns={"value": "Value", "end_time": "Date"}, inplace=True)
        return df, df["Value"].sum(), None
    else:
        res = fetch_total_value(metric)
        if "error" in res or not res.get("data"):
            return None, None, res.get("error", {}).get("message", "No data")
        val = res["data"][0]["total_value"].get("value", 0)
        today = pd.to_datetime("today").normalize()
        df = pd.DataFrame([{"Date": today, "Value": val}])
        return df, val, None
    
#Insights functions
def get_account_insights(IG_USER_ID, access_token):

    url = f"https://graph.facebook.com/v18.0/{IG_USER_ID}/insights"

    # Only metrics that actually work with period=day
    metrics = [
        "reach"  # only one reliably working as of API v18
    ]

    params = {
        "metric": ",".join(metrics),
        "period": "days_28",
        "access_token": access_token
    }

    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json().get("data", [])
    else:
        print("❌ Error fetching account insights:", response.status_code, response.text)
        return []
 
def get_ig_business_account_id(page_id, access_token):
    url = f'https://graph.facebook.com/v19.0/{page_id}'
    params = {
        'fields': 'instagram_business_account',
        'access_token': access_token
    }
    response = requests.get(url, params=params)
    data = response.json()
    return data.get('instagram_business_account', {}).get('id')

def get_profile_info(IG_USER_ID, access_token):
    url = f'https://graph.facebook.com/v19.0/{IG_USER_ID}'
    params = {
        'fields': 'username,name,biography,website,profile_picture_url,followers_count,media_count',
        'access_token': access_token
    }
    response = requests.get(url, params=params)
    return response.json()

def get_recent_posts(IG_USER_ID, access_token):
    url = f'https://graph.facebook.com/v19.0/{IG_USER_ID}/media'
    params = {
        'fields': 'id,caption,media_type,media_url,timestamp,like_count,comments_count',
        'access_token': access_token
    }
    response = requests.get(url, params=params)
    return response.json().get('data', [])

def get_status(user_name):
    response = supabase.table("user_info") \
        .select("account_status, total_token_limit, tokens_used, subscription_type") \
        .eq("user_name", user_name) \
        .execute()
    return response.data[0] if response.data else (None, None, None)

def fetch_otp(user_name):
    response = supabase.table("otp") \
        .select("otp_generated") \
        .eq("user_name", user_name) \
        .execute()
    print(f"Fetched OTP for {user_name}: {response}", flush=True)

    if response.data and isinstance(response.data, list) and len(response.data) > 0:
        return response.data[0].get("otp_generated")
    return None

#User authentication
def login_user(username, password):
    response = supabase.table("user_info").select("*").eq("user_name", username).eq("password", password).execute()
    if response.data:
        return response.data[0]  # Return first matching user
    return None

def get_user_info(user_name):
    response = supabase.table("user_info").select("*").eq("user_name", user_name).execute()
    return response.data[0] if response.data else {}

# Step 1: Generate OTP
def generate_otp():
    return str(random.randint(100000, 999999))

# Step 2: Send OTP Email
def send_otp_email(receiver_email, otp):
    sender_email = "automatexpos@gmail.com"  # use a dedicated Gmail
    app_password = st.secrets["app_password"]

    msg = EmailMessage()
    msg.set_content(f"Your OTP code is: {otp}")
    msg["Subject"] = "Your OTP Code"
    msg["From"] = sender_email
    msg["To"] = receiver_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender_email, app_password)
            smtp.send_message(msg)
        print(f"OTP sent to {receiver_email}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


if st.session_state.logged_in:
    # Always fetch latest user info for token checks
    db_user = get_user_info(st.session_state.user_data["user_name"])
    is_trial = db_user.get("is_trial")
    tokens_used = int(db_user.get("tokens_used", 0))
    total_token_limit = int(db_user.get("total_token_limit", 0))
    tokens_left = total_token_limit - tokens_used

# Toggle for login/signup
if not st.session_state.logged_in:
    auth_mode = st.sidebar.radio(
    "Choose mode",
    ["Login", "Signup", "Pricing", "Support"],
    index=["Login", "Signup", "Pricing", "Support"].index(st.session_state.get("page", "Login")))
    st.title("🔐 Instagram Manager")
    if auth_mode == "Login":

        entered_username = st.text_input("Username", key="login_username")
        entered_password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login"):
            user = login_user(entered_username, entered_password)

            if user:
                st.session_state.logged_in = True
                st.session_state.user_data = user
                st.success("Login successful!")
                st.rerun()
            else:
                st.error("Invalid username or password.")

        st.write("Don't have an account? Please signup to continue.")    

    elif auth_mode == "Support":
        st.info("Please share your username and email address when writing to us for faster resolution.")        
        st.title("🛠️ Support")
        st.write("-----------------------------------------------------")
        st.write("For any issues or queries, please contact us at:")
        st.write("Email: support@automatexpos.com")
        st.write("-----------------------------------------------------")
        st.write("To upgrage your subscription, please contact us at:")
        st.write("Email: upgrade@automatexpos.com")

        st.markdown(
            "<hr style='margin-top:2em;'/>"
            "<div style='text-align:center; color:gray;'>"
            "AutomateXpo<br>"
            "<a href='https://calendly.com/automatexpos/30min' target='_blank' style='color:#3366cc;'>📅 Schedule a call with us</a>"
            "</div>",
            unsafe_allow_html=True
        )        
        # Embed Tawk.to widget
        components.html(
            """
            <!--Start of Tawk.to Script-->
            <script type="text/javascript">
            var Tawk_API=Tawk_API||{}, Tawk_LoadStart=new Date();
            (function(){
            var s1=document.createElement("script"),s0=document.getElementsByTagName("script")[0];
            s1.async=true;
            s1.src='https://embed.tawk.to/688ce23e394cad192dfa649d/1j1j57hsj';
            s1.charset='UTF-8';
            s1.setAttribute('crossorigin','*');
            s0.parentNode.insertBefore(s1,s0);
            })();
            </script>
            <!--End of Tawk.to Script-->
            """,
            height=0,  # Keep hidden
            scrolling=False  # Keeps the component hidden
        )

    elif auth_mode == "Pricing":
        st.title("💰 Pricing Plans")
        st.write("""
            - **Trial - 7 posts**: Free for 7 posts.
            - **Standard**: $30/month for 60 posts.
            - **Premium**: $50/month for 120 posts.
        """)
        st.warning("Please signup to choose a plan.")

    else:  # Signup mode
        entered_username = st.text_input("Username", key="login_username")
        entered_password = st.text_input("Password", type="password", key="login_password")
        email_address = st.text_input("Email Address", value="", key="signup_email")
        subscription_type = st.selectbox("Subscription Type", ["Trial - 7 posts", "Standard", "Premium"], index=0)

        if subscription_type == "Trial - 7 posts":
            total_token_limit = 7
            is_trial = True
        elif subscription_type == "Standard":
            total_token_limit = 60
        elif subscription_type == "Premium":
            total_token_limit = 120

        def is_valid_email(email):
            # Simple regex for email validation
            return re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email)

        # ...existing code...
        if st.button("Sign up"):
            if not entered_username or not entered_password or not email_address:
                st.error("Please fill in all fields.")
                st.stop()
            if not is_valid_email(email_address):
                st.error("Please enter a valid email address.")
                st.stop()

            # Check if username or email already exists in user_info
            existing = (
                supabase.table("user_info")
                .select("user_name, email_address")
                .or_(f"user_name.eq.{entered_username},email_address.eq.{email_address}")
                .execute()
            )

            if existing.data:
                st.error("Username/Email already taken.")
            else:
                # Generate OTP
                with st.spinner("Generating OTP..."):
                    otp = generate_otp()
                    otp_entry = supabase.table("otp").select("user_name").eq("user_name", entered_username).execute()
                    if otp_entry.data:
                        supabase.table("otp").update({
                            "otp_generated": otp,
                            "created_at": datetime.now().isoformat()
                        }).eq("user_name", entered_username).execute()
                    else:
                        supabase.table("otp").insert({
                            "user_name": entered_username,
                            "otp_generated": otp,
                            "created_at": datetime.now().isoformat()
                        }).execute()
                    send_otp_email(email_address, otp)
                    st.success("OTP sent to your email address.")
                    st.session_state.otp_generated = True  # <-- Set flag

        # Show OTP input and verify button if OTP was generated
        if st.session_state.get("otp_generated"):
            entered_otp = st.text_input("Enter OTP received on your email", key="otp_input")
            if st.button("Verify OTP"):
                otp_value = fetch_otp(entered_username)
                print("OTP fetched is : ", otp_value)  # Debugging line
                if otp_value and entered_otp == str(otp_value):
                    st.success("OTP verified successfully!")
                    # Insert new user
                    supabase.table("user_info").insert({
                        "user_name": entered_username,
                        "password": entered_password,
                        "email_address": email_address,
                        "account_status": "Pending",
                        "subscription_type": subscription_type,
                        "total_token_limit": total_token_limit,
                        "tokens_used": 0,
                        "num_of_posts": 1,  # Default value
                        "frequency": "Daily",  # Default value
                        "dontuseuntil": 90,  # Default value
                        "is_trial": is_trial if 'is_trial' in locals() else False,
                    }).execute()
                    supabase.table("business_profile").insert({
                        "user_name": entered_username
                    }).execute()
                    st.balloons()
                    time.sleep(2)
                    st.success("Signup successful! Please Login to continue.")
                    st.session_state.otp_generated = False  # Reset flag
                    time.sleep(5)
                    st.rerun()
                else:
                    st.error("Invalid OTP. Please try again.")
                    if st.button("Resend OTP"):
                        otp = generate_otp()
                        supabase.table("otp").update({"otp_generated": otp}).eq("user_name", entered_username).execute()
                        send_otp_email(email_address, otp)
                        st.success("OTP resent to your email address.")
                    st.stop()
else:

    user_data = st.session_state.user_data
    business_response = supabase.table("business_profile").select("business_name").eq("user_name", user_data["user_name"]).execute()
    business_name = business_response.data[0]["business_name"] if business_response.data and business_response.data[0].get("business_name") else None

    config_complete = bool(user_data.get("inst_access_token")) and bool(user_data.get("ig_user_id")) and bool(business_name)

    # Build menu options based on config status
    # Hide menus if user has no tokens left
    if tokens_left <= 0:
        st.warning("⚠️ You have used all your available tokens. Upgrade to continue posting.")
        menu_options = ["Account Status", "Scheduled Posts", "Logout"]
    else:
        menu_options = ["Account Status", "Configuration", "Business information", "Logout"]
        if config_complete:
            menu_options.insert(1, "Home")
            menu_options.insert(2, "Analytics")
            menu_options.insert(3, "Detailed Insights")
            menu_options.insert(4, "Scheduled Posts")


    menu = st.sidebar.selectbox(
        "Select a page:",
        menu_options
    )

    # Optionally, show a warning if config is incomplete
    if not config_complete and menu not in ["Configuration", "Business information", "Logout"]:      
        st.warning("Please complete your configuration before accessing analytics or scheduling features.")

    # Display content based on menu selection
    if menu == "Home":
        with st.spinner("Loading home page..."):
            time.sleep(3)

        st.title("📱 Instagram Manager")
        st.write("Welcome to the Home page!")

        st.header("Select schedule criteria")
        num_of_posts = st.number_input("Number of posts per interval", min_value=1, step=1, format="%d")
        frequency = st.selectbox("Post frequency", ["Daily", "Weekly", "Monthly"])
        dont_use_until = st.number_input(f"Do not use for next - Days", min_value=90, step=1, format="%d")
        posting_hours = st.text_input("Posting hours",placeholder="9:00, 11:00, 17:00")

        if st.button("Update Critera"):
            update_posting_configs(
                st.session_state.user_data["user_name"],
                num_of_posts,
                frequency,
                dont_use_until,
                posting_hours
            )
            st.success("Configuration updated successfully!")
            time.sleep(2)
            st.rerun()
        st.header("Current Critera")
        configs = fetch_posting_configs(st.session_state.user_data["user_name"])
        dont_use_until1 = configs[2]
        num_of_posts1 = configs[0]
        frequency1 = configs[1]
        posting_hours = configs[3]
        st.write(f"Don't use for the next {dont_use_until1} days")
        st.write(f"Number of posts: {num_of_posts1}")
        st.write(f"Frequency: {frequency1}")  
        st.write("Posting hours:", posting_hours)

    elif menu == "Business information":
        with st.spinner("Loading business information..."):
            time.sleep(3)
        st.title("🏢 Business Information")
        user_name = st.session_state.user_data["user_name"]

        # Fetch business info from the table
        response = supabase.table("business_profile") \
            .select("*") \
            .eq("user_name", user_name) \
            .execute()
        business_info = response.data[0] if response.data else {}

        # Input fields (pre-filled if data exists)
        business_name = st.text_input("Business Name", value=business_info.get("business_name", ""), key="business_name")
        business_intro = st.text_input("Business introduction", value=business_info.get("business_introduction", ""), key="business_introduction")
        prod_services = st.text_input("Products/Services Description", value=business_info.get("products_services", ""), key="products_services")

        if st.button("Save Business Information"):
            if business_name and business_intro and prod_services:
                # If record exists, update; else, insert
                if business_info:
                    supabase.table("business_profile").update({
                        "business_name": business_name,
                        "business_introduction": business_intro,
                        "products_services": prod_services
                    }).eq("user_name", user_name).execute()
                    st.success("Business information updated successfully!")
                else:
                    supabase.table("business_profile").insert({
                        "user_name": user_name,
                        "business_name": business_name,
                        "business_introduction": business_intro,
                        "products_services": prod_services
                    }).execute()
                    st.success("Business information saved successfully!")
            else:
                st.warning("Please fill in all fields.")

    elif menu == "Account Status":
        with st.spinner("Loading account status..."):
            time.sleep(3)

        st.title("📊 Account Status")
        status = get_status(st.session_state.user_data["user_name"])
        if status:
            st.write(f"**Account Name:** {st.session_state.user_data['user_name']}")
            st.write(f"**Account Status:** {status.get('account_status', 'N/A')}")
            st.write(f"**Subscription Type:** {status.get('subscription_type', 'N/A')}")
            st.write(f"**Total Posts Limit:** {status.get('total_token_limit', 'N/A')}")
            st.write(f"**Posts Used:** {status.get('tokens_used', 'N/A')}")
        else:
            st.write("No account status found.")

    elif menu == "Analytics":
        with st.spinner("Loading analytics..."):
            time.sleep(3)
        st.title("📊 Analytics Dashboard")
        tab1, tab2 = st.tabs(["📄 Profile Info", "📸 Recent Posts"])

        with tab1:
            profile = get_profile_info(IG_USER_ID, ACCESS_TOKEN)

            st.subheader(f"Username: {profile.get('username')}")
            st.write(f"**Name:** {profile.get('name')}")
            st.write(f"**Biography:** {profile.get('biography')}")
            st.write(f"**Website:** {profile.get('website')}")
            st.image(profile.get('profile_picture_url'), width=150)
            st.write(f"**Followers Count:** {profile.get('followers_count')}")
            st.write(f"**Total Media Posts:** {profile.get('media_count')}")

        with tab2:
            posts = get_recent_posts(IG_USER_ID, ACCESS_TOKEN)

            for i in range(0, len(posts), 3):
                cols = st.columns(3)
                for j in range(3):
                    if i + j < len(posts):
                        post = posts[i + j]
                        with cols[j]:
                            st.markdown("---")
                            st.write(f"**Post ID:** {post['id']}")
                            # st.write(f"**Caption:** {post.get('caption', 'N/A')}")
                            st.write(f"**Media Type:** {post['media_type']}")
                            if post['media_type'] == "IMAGE":
                                st.image(post['media_url'], width=300)
                            elif post['media_type'] == "VIDEO":
                                st.video(post['media_url'])
                            elif post['media_type'] == "CAROUSEL_ALBUM":
                                st.write("Carousel post. [View Media]({})".format(post['media_url']))
                            else:
                                st.write(f"Media URL: {post['media_url']}")
                            # st.write(f"**Timestamp:** {post['timestamp']}")
                            ts = post['timestamp']
                            
                            try:
                                # Fix timezone format for fromisoformat
                                ts_fixed = ts.replace("+0000", "+00:00")
                                dt = datetime.fromisoformat(ts_fixed)
                                st.write(f"**Date:** {dt.date()} | **Time:** {dt.strftime('%H:%M:%S')}")
                            except Exception:
                                st.write(f"**Timestamp:** {ts}")                       
                            st.write(f"**Like Count:** {post.get('like_count', 'N/A')}")
                            st.write(f"**Comments Count:** {post.get('comments_count', 'N/A')}")

    elif menu == "Detailed Insights":
        with st.spinner("Loading detailed insights..."):
            time.sleep(3)
        # Metrics we want to show
        METRICS = [
            "views", "reach", "likes", "comments", "shares",
            "saves", "replies", "accounts_engaged", "total_interactions"
        ]

        # Metrics that support time_series
        TIME_SERIES_SUPPORTED = ["reach"]

        # Fetch total_value (default)
        def fetch_total_value(metric):
            params = {
                "metric": metric,
                "period": "day",
                "metric_type": "total_value",
                "access_token": ACCESS_TOKEN
            }
            r = requests.get(BASE_URL, params=params)
            return r.json()

        def fetch_total_value_lifetime(metric):
            params = {
                "metric": metric,
                "period": "day",  # or "day", "days_28"
                "metric_type": "total_value",
                "access_token": ACCESS_TOKEN
            }
            r = requests.get(BASE_URL, params=params)
            return r.json()

        # Fetch time_series (only for reach)
        def fetch_time_series(metric):
            params = {
                "metric": metric,
                "period": "day",  # or "day", "week"
                "metric_type": "time_series",
                "access_token": ACCESS_TOKEN
            }
            r = requests.get(BASE_URL, params=params)
            return r.json()

        # Process total or time-series data
        def get_metric_data(metric):
            if metric in TIME_SERIES_SUPPORTED:
                res = fetch_time_series(metric)
                if "error" in res or not res.get("data"):
                    return None, None, res.get("error", {}).get("message", "No data")
                values = res["data"][0].get("values", [])
                df = pd.DataFrame(values)
                df["end_time"] = pd.to_datetime(df["end_time"])
                df.rename(columns={"value": "Value", "end_time": "Date"}, inplace=True)
                return df, df["Value"].sum(), None
            else:
                res = fetch_total_value(metric)
                if "error" in res or not res.get("data"):
                    return None, None, res.get("error", {}).get("message", "No data")
                val = res["data"][0]["total_value"].get("value", 0)
                today = pd.to_datetime("today").normalize()
                df = pd.DataFrame([{"Date": today, "Value": val}])
                return df, val, None

        def get_aggregated_metric(metric):
            url = f"https://graph.facebook.com/{API_VERSION}/{IG_USER_ID}/media"
            params = {
                "fields": f"{metric}",
                "access_token": ACCESS_TOKEN,
                "limit": 100  # adjust as needed
            }
            r = requests.get(url, params=params)
            data = r.json().get("data", [])
            return sum(item.get(metric, 0) for item in data)


        st.title("📊 Instagram Insights Dashboard")

        tab1, tab2 = st.tabs(["📋 Table View", "📈 Charts View"])

        # --- TAB 1: TABLE VIEW ---
        with tab1:
            METRIC_FIELD_MAP = {
                "likes": "like_count",
                "comments": "comments_count",
                # "shares": "shares_count",  # Only if available
            }    
            st.subheader("📋 Summary Table")
            rows = []
            # List of metrics to aggregate from media
            AGGREGATE_FROM_MEDIA = list(METRIC_FIELD_MAP.keys())

            for metric in METRICS:
                if metric in AGGREGATE_FROM_MEDIA:
                    field = METRIC_FIELD_MAP[metric]
                    val = get_aggregated_metric(field)
                    err = None
                else:
                    _, val, err = get_metric_data(metric)
                rows.append({
                    "Metric": metric.replace("_", " ").title(),
                    "Value": val if val is not None else f"⚠️ {err}"
                })
            st.table(pd.DataFrame(rows))

            with tab2:
                st.subheader("📈 Metric Visualizations")

                # Each row contains 3 charts
                col_index = 0
                chart_cols = st.columns(2)

                # Define a funnel order if you want to show a funnel
                FUNNEL_METRICS = ["reach", "accounts_engaged", "total_interactions"]

                # Prepare funnel data
                funnel_data = []
                for metric in FUNNEL_METRICS:
                    _, val, err = get_metric_data(metric)
                    funnel_data.append({"Metric": metric.replace("_", " ").title(), "Value": val if val is not None else 0})

                for idx, metric in enumerate(METRICS):
                    col = chart_cols[col_index]
                    with col:
                        st.markdown(f"#### {metric.replace('_', ' ').title()}")

                        # Area chart for time series
                        if metric in TIME_SERIES_SUPPORTED:
                            df_ts, _, err = get_metric_data(metric)
                            if err:
                                st.warning(f"{metric}: {err}")
                            elif df_ts is not None:
                                # Convert to date only and group by date (in case there are multiple times per day)
                                df_ts["Date"] = pd.to_datetime(df_ts["Date"]).dt.date
                                df_ts = df_ts.groupby("Date", as_index=False)["Value"].sum()
                                # Sort by date ascending
                                df_ts = df_ts.sort_values("Date", ascending=True)
                                st.write(df_ts)  # Add this line to inspect your data
                                fig = px.bar(df_ts, x="Date", y="Value", title=metric.replace("_", " ").title())
                                st.plotly_chart(fig, use_container_width=True)

                        # Funnel chart for the funnel metrics (only show once)
                        elif metric == FUNNEL_METRICS[0]:
                            df_funnel = pd.DataFrame(funnel_data)
                            fig = px.funnel(df_funnel, x="Value", y="Metric", title="Funnel: Reach → Engaged → Interactions")
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            if metric in AGGREGATE_FROM_MEDIA:
                                field = METRIC_FIELD_MAP[metric]
                                total = get_aggregated_metric(field)
                                df = pd.DataFrame([{"Metric": metric.replace("_", " ").title(), "Value": total}])
                                fig = px.bar(df, x="Metric", y="Value", title=f"{metric.replace('_', ' ').title()} (Aggregated)")
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                # Try breakdowns for donut chart
                                res = fetch_total_value(metric)

                                if "error" in res or not res.get("data"):
                                    st.warning(f"{metric}: {res.get('error', {}).get('message', 'No data')}")
                                else:
                                    item = res["data"][0]
                                    breakdowns = item["total_value"].get("breakdowns", [])
                                    if breakdowns:
                                        breakdown_data = []
                                        for br in breakdowns:
                                            for r in br["results"]:
                                                dims = " | ".join(r["dimension_values"])
                                                breakdown_data.append({"Category": dims, "Value": r["value"]})
                                        df = pd.DataFrame(breakdown_data)
                                        if not df.empty:
                                            fig = px.pie(df, names="Category", values="Value", hole=0.4)
                                            st.plotly_chart(fig, use_container_width=True)
                                        else:
                                            st.info("No breakdown data available.")
                                    else:
                                        # Just show total as bar
                                        total = item["total_value"].get("value", 0)
                                        df = pd.DataFrame([{"Metric": metric, "Value": total}])
                                        fig = px.bar(df, x="Metric", y="Value")
                                        st.plotly_chart(fig, use_container_width=True)

                    col_index = (col_index + 1) % 2
                    if col_index == 0 and idx != len(METRICS) - 1:
                        chart_cols = st.columns(2)
        st.markdown("----")

    elif menu == "Scheduled Posts":
        with st.spinner("Loading scheduled posts..."):
            time.sleep(3)
        st.title("📅 Scheduled Posts Calendar View")
        tab1, tab2 = st.tabs(["📅 Calendar View", "📝 Manage Scheduled Posts"])
        with tab1:
            posts = get_all_posts(st.session_state.user_data["user_name"])
            # print("Fetched posts", posts)

            if posts:
                # Transform posts into calendar events
                calendar_events = []
                for post in posts:
                    # Create a hover-friendly string with ID, status, caption
                    hover_text = (
                        f"ID: {post['id']}\n"
                        f"Status: {post['posted']}\n"
                        
                        # f"Caption: {post.get('caption', 'No caption')}"
                    )
                    
                    calendar_events.append({
                        "title": hover_text,  # This will show on hover
                        "start": post['scheduled_time'],
                        "color": "#28a745" if post["posted"] else "#ffc107",
                    })
                
                options = {
                    "initialView": "dayGridMonth",
                    "editable": False,
                    "selectable": False,
                    "height": 650,
                    "headerToolbar": {
                        "left": "prev,next today",
                        "center": "title",
                        "right": "dayGridMonth,timeGridWeek,timeGridDay"
                    },
                    "eventTimeFormat": {
                        "hour": "numeric",
                        "minute": "2-digit",
                        "meridiem": "short",
                        "hour12": True
                    }
                }

                calendar(events=calendar_events, options=options)

            else:
                st.info("No scheduled posts found.")

            with tab2:
                st.subheader("Manage Scheduled Posts")
                posts = sorted(posts, key=lambda x: x['id'], reverse=True)

                for post in posts:
                    with st.expander(f"📌 Post ID {post['id']}", expanded=False):
                        action_col1, action_col2, action_col3 = st.columns([6, 2, 2])
                        with action_col1:
                            st.write(
                                f"**ID:** {post['id']} | "
                                f"**Time:** {post['scheduled_time']} | "
                                f"**Status:** {post['posted']} |"
                            )

                        with action_col2:
                            if st.button("Delete", key=f"delete_{post['id']}"):
                                delete_post(post['id'])
                                st.success(f"Deleted post ID {post['id']}")
                                st.rerun()

                        with action_col3:
                            edit_date = st.checkbox("✏️ Edit Date", key=f"edit_date_toggle_{post['id']}")

                        if edit_date:
                            post_dt = (
                                datetime.fromisoformat(post['scheduled_time'])
                                if isinstance(post['scheduled_time'], str)
                                else post['scheduled_time']
                            )
                            new_date = st.date_input(f"Date", value=post_dt.date())
                            new_time = st.time_input(f"Time", value=post_dt.time())
                            new_datetime = datetime.combine(new_date, new_time)

                            if new_datetime != post_dt:
                                if st.button("Save New Time", key=f"save_{post['id']}"):
                                    update_post(post['id'], 'scheduled_time', new_datetime)
                                    st.success(f"Updated post ID {post['id']} to {new_datetime}")
                                    time.sleep(1)
                                    st.rerun()

                        # Layout for caption and image
                        left_col, right_col = st.columns([3, 1])

                        with left_col:
                            if post.get("caption"):
                                default_caption = post.get("caption", "")
                                new_caption = st.text_area(
                                    "Edit Caption",
                                    value=default_caption,
                                    key=f"caption_input_{post['id']}",
                                    height=150,
                                )

                                if new_caption != default_caption:
                                    if st.button("Update Caption", key=f"update_caption_{post['id']}"):
                                        update_post(post['id'], 'caption', new_caption)
                                        st.success("Caption updated successfully.")
                                        time.sleep(1)
                                        st.rerun()

                        with right_col:
                            if post.get("image_url"):
                                st.image(post["image_url"], width=150, caption="Preview")

    elif menu == "Configuration":
        with st.spinner("Loading configuration..."):
            time.sleep(3)
        st.title("🔧 Configuration Setup")
        st.write("Configure your API keys and credentials.")

        user_name = st.session_state.user_data["user_name"]

        # Fetch current keys if exist
        response = supabase.table("user_info") \
            .select("*") \
            .eq("user_name", user_name) \
            .execute()

        user_data = response.data[0] if response.data else {}

        # Input fields (pre-filled if data exists)
        # open_ai_key = st.text_input("OpenAI API Key", value=user_data.get("open_ai_key", ""))
        st.markdown('[Create Instagram App](https://www.youtube.com/watch?v=BuF9g9_QC04)')
        access_token = st.text_input("Instagram Extended Access Token", value=user_data.get("inst_access_token", ""))
        ig_user_id = st.text_input("Instagram Business User ID", value=user_data.get("ig_user_id", ""))
        st.markdown('[Create Cloudinary account](https://cloudinary.com/users/register_free)')
        cloud_name = st.text_input("Cloudinary Cloud Name", value=user_data.get("cloudinary_cloud_name", ""))
        cloud_key = st.text_input("Cloudinary API Key", value=user_data.get("cloudinary_api_key", ""))
        cloud_secret = st.text_input("Cloudinary API Secret", value=user_data.get("cloudinary_api_secret", ""), type="password")

        if st.button("Save Configuration"):
            if not access_token or not ig_user_id or not cloud_name or not cloud_key or not cloud_secret:
                st.error("Please fill in all fields.")
                st.stop()

            update_fields = {
                # "open_ai_key": open_ai_key,
                "inst_access_token": access_token,
                "ig_user_id": ig_user_id,
                "cloudinary_cloud_name": cloud_name,  # <-- FIXED KEY HERE
                "cloudinary_api_key": cloud_key,
                "cloudinary_api_secret": cloud_secret
            }

            supabase.table("user_info").update(update_fields).eq("user_name", user_name).execute()
            st.success("Configuration saved successfully!")
            # Refresh session state
            updated = supabase.table("user_info").select("*").eq("user_name", user_name).execute()
            st.session_state.user_data = updated.data[0]
            st.rerun()

    elif menu == "Logout":
        with st.spinner("Logging out..."):
            time.sleep(2)
        st.session_state.logged_in = False
        st.session_state.page = "Login"  # Or "Support" if you want to redirect to support
        st.success("You have been logged out successfully.")
        st.rerun()
