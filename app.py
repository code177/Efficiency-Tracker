import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
import plotly.graph_objects as go
import plotly.express as px
import os
import hashlib
import uuid
from datetime import timedelta

# Page Configuration
st.set_page_config(
    page_title="Tracker",
    page_icon="📚",
    layout="wide"
)


# ============================================================================
# PERSISTENT AUTHENTICATION SYSTEM
# ============================================================================

def init_auth_database():
    """Initialize authentication and device tracking database"""
    conn = sqlite3.connect('study_tracker.db')
    c = conn.cursor()
    
    # Devices table - tracks approved devices
    c.execute('''CREATE TABLE IF NOT EXISTS authorized_devices
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  device_id TEXT UNIQUE NOT NULL,
                  device_name TEXT,
                  ip_address TEXT,
                  user_agent TEXT,
                  first_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  is_approved INTEGER DEFAULT 0,
                  session_token TEXT,
                  token_expiry TIMESTAMP)''')
    
    # Login attempts table - tracks all login attempts
    c.execute('''CREATE TABLE IF NOT EXISTS login_attempts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  device_id TEXT,
                  ip_address TEXT,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  status TEXT,
                  user_agent TEXT)''')
    
    conn.commit()
    conn.close()

def get_device_fingerprint():
    """Generate unique device fingerprint"""
    if 'device_id' not in st.session_state:
        device_id = str(uuid.uuid4())
        st.session_state.device_id = device_id
    return st.session_state.device_id

def get_client_info():
    """Extract client information"""
    try:
        headers = st.context.headers
        return {
            'ip_address': headers.get('X-Forwarded-For', headers.get('Remote-Addr', 'Unknown')),
            'user_agent': headers.get('User-Agent', 'Unknown'),
        }
    except:
        return {
            'ip_address': 'Unknown',
            'user_agent': 'Unknown'
        }

def generate_session_token():
    """Generate secure session token"""
    return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()

def save_device_session(device_id, client_info, approved=False):
    """Save device session to database"""
    conn = sqlite3.connect('study_tracker.db')
    c = conn.cursor()
    
    session_token = generate_session_token()
    token_expiry = (datetime.now() + timedelta(days=30)).isoformat()
    
    c.execute("SELECT id FROM authorized_devices WHERE device_id = ?", (device_id,))
    existing = c.fetchone()
    
    if existing:
        c.execute('''UPDATE authorized_devices 
                     SET last_login = CURRENT_TIMESTAMP,
                         session_token = ?,
                         token_expiry = ?,
                         ip_address = ?,
                         user_agent = ?
                     WHERE device_id = ?''',
                  (session_token, token_expiry, client_info['ip_address'], 
                   client_info['user_agent'], device_id))
    else:
        device_name = f"Device {client_info['ip_address'][:15]}"
        c.execute('''INSERT INTO authorized_devices 
                     (device_id, device_name, ip_address, user_agent, 
                      session_token, token_expiry, is_approved)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (device_id, device_name, client_info['ip_address'], 
                   client_info['user_agent'], session_token, token_expiry, 
                   1 if approved else 0))
    
    conn.commit()
    conn.close()
    
    return session_token

def check_device_approval(device_id):
    """Check if device is approved"""
    conn = sqlite3.connect('study_tracker.db')
    c = conn.cursor()
    
    c.execute('''SELECT is_approved, session_token, token_expiry 
                 FROM authorized_devices 
                 WHERE device_id = ?''', (device_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        is_approved, token, expiry = result
        if expiry and datetime.fromisoformat(expiry) > datetime.now():
            return bool(is_approved), token
    
    return False, None

def log_login_attempt(device_id, client_info, status):
    """Log login attempt"""
    conn = sqlite3.connect('study_tracker.db')
    c = conn.cursor()
    
    c.execute('''INSERT INTO login_attempts 
                 (device_id, ip_address, status, user_agent)
                 VALUES (?, ?, ?, ?)''',
              (device_id, client_info['ip_address'], status, client_info['user_agent']))
    
    conn.commit()
    conn.close()

def check_password():
    """Returns `True` if the user had the correct password - WITH DEVICE TRACKING."""
    
    # Initialize auth database
    init_auth_database()
    
    # Get device fingerprint
    device_id = get_device_fingerprint()
    client_info = get_client_info()
    
    # Check if already authenticated in session
    if 'authenticated' in st.session_state and st.session_state.authenticated:
        return True
    
    # Check if device is approved with valid session
    is_approved, session_token = check_device_approval(device_id)
    
    if is_approved and session_token:
        # Device is approved and has valid session - AUTO LOGIN!
        st.session_state.authenticated = True
        st.session_state.device_id = device_id
        st.session_state.session_token = session_token
        log_login_attempt(device_id, client_info, "Auto-login Success")
        return True
    
    # Show login form
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        entered_password = st.session_state["password"]
        hashed_input = hashlib.sha256(entered_password.encode()).hexdigest()
        
        # Get the correct password hash from secrets (YOUR EXISTING HASH WORKS!)
        try:
            correct_hash = st.secrets["password"]["hash"]
        except:
            # Fallback for local testing
            correct_hash = hashlib.sha256("jee2025".encode()).hexdigest()
        
        if hashed_input == correct_hash:
            # Password correct - save device if "remember" is checked
            if st.session_state.get("remember_device", True):
                session_token = save_device_session(device_id, client_info, approved=True)
                st.session_state.session_token = session_token
            
            st.session_state["password_correct"] = True
            st.session_state.authenticated = True
            st.session_state.device_id = device_id
            
            log_login_attempt(device_id, client_info, "Login Success")
            del st.session_state["password"]  # Don't store password
        else:
            log_login_attempt(device_id, client_info, "Login Failed - Wrong Password")
            st.session_state["password_correct"] = False

    # Return True if password is correct
    if st.session_state.get("password_correct", False):
        return True

    # Show login form
    st.markdown("# 🔐 Tracker Login")
    st.markdown("### Enter password to access your dashboard")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        # Show device info
        with st.expander("🔍 Your Device Info", expanded=False):
            st.caption(f"**Device ID:** `{device_id[:16]}...`")
            st.caption(f"**IP Address:** `{client_info['ip_address']}`")
            st.caption(f"**Browser:** `{client_info['user_agent'][:50]}...`")
        
        st.text_input(
            "Password", 
            type="password", 
            on_change=password_entered, 
            key="password",
            placeholder="Enter your password"
        )
        
        # Remember device checkbox
        st.checkbox("🔒 Trust this device (stay logged in for 30 days)", 
                   value=True, 
                   key="remember_device")
        
        if "password_correct" in st.session_state and not st.session_state["password_correct"]:
            st.error("😕 Incorrect password. Please try again.")
        
        st.info("💡 Tip: Contact admin if you forgot your password")
    
    return False


# Password Protection Function
def check_password():
    """Returns `True` if the user had the correct password."""
    
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        # Hash the entered password
        entered_password = st.session_state["password"]
        hashed_input = hashlib.sha256(entered_password.encode()).hexdigest()
        
        # Get the correct password hash from secrets
        try:
            correct_hash = st.secrets["password"]["hash"]
            if hashed_input == correct_hash:
                st.session_state["password_correct"] = True
                del st.session_state["password"]  # Don't store password
            else:
                st.session_state["password_correct"] = False
        except:
            # Fallback for local testing (you can remove this after deployment)
            if entered_password == "jee2025":
                st.session_state["password_correct"] = True
                del st.session_state["password"]
            else:
                st.session_state["password_correct"] = False

    # Return True if password is correct
    if st.session_state.get("password_correct", False):
        return True

    # Show login form
    st.markdown("# 🔐 Tracker Login")
    st.markdown("### Enter password to access your dashboard")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input(
            "Password", 
            type="password", 
            on_change=password_entered, 
            key="password",
            placeholder="Enter your password"
        )
        
        if "password_correct" in st.session_state and not st.session_state["password_correct"]:
            st.error("😕 Incorrect password. Please try again.")
        
        st.info("💡 Tip: Contact admin if you forgot your password")
    
    return False

# Check password before showing app
if not check_password():
    st.stop()  # Don't run the rest of the app



# ============================================================================
# ADMIN PANEL FUNCTIONS
# ============================================================================

def get_all_devices():
    """Get all registered devices"""
    conn = sqlite3.connect('study_tracker.db')
    try:
        df = pd.read_sql_query('''
            SELECT id, device_id, device_name, ip_address, 
                   first_login, last_login, is_approved,
                   CASE 
                       WHEN datetime(token_expiry) > datetime('now') THEN 'Active'
                       ELSE 'Expired'
                   END as session_status
            FROM authorized_devices 
            ORDER BY last_login DESC
        ''', conn)
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def get_login_history(limit=50):
    """Get recent login attempts"""
    conn = sqlite3.connect('study_tracker.db')
    try:
        df = pd.read_sql_query('''
            SELECT la.timestamp, la.device_id, la.ip_address, 
                   la.status, ad.device_name
            FROM login_attempts la
            LEFT JOIN authorized_devices ad ON la.device_id = ad.device_id
            ORDER BY la.timestamp DESC
            LIMIT ?
        ''', conn, params=(limit,))
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def approve_device(device_id):
    """Approve a device for access"""
    conn = sqlite3.connect('study_tracker.db')
    c = conn.cursor()
    c.execute("UPDATE authorized_devices SET is_approved = 1 WHERE device_id = ?", 
              (device_id,))
    conn.commit()
    conn.close()

def revoke_device(device_id):
    """Revoke device access"""
    conn = sqlite3.connect('study_tracker.db')
    c = conn.cursor()
    c.execute("UPDATE authorized_devices SET is_approved = 0 WHERE device_id = ?", 
              (device_id,))
    conn.commit()
    conn.close()

def delete_device(device_id):
    """Delete device completely"""
    conn = sqlite3.connect('study_tracker.db')
    c = conn.cursor()
    c.execute("DELETE FROM authorized_devices WHERE device_id = ?", (device_id,))
    c.execute("DELETE FROM login_attempts WHERE device_id = ?", (device_id,))
    conn.commit()
    conn.close()

def show_admin_panel():
    """Display admin panel for device management - ONLY PASSWORD HOLDERS ARE ADMINS"""
    
    st.sidebar.divider()
    
    if st.sidebar.button("⚙️ Admin Panel", use_container_width=True):
        st.session_state.show_admin = not st.session_state.get('show_admin', False)
    
    if st.session_state.get('show_admin', False):
        st.markdown("---")
        st.header("⚙️ Admin Device Management")
        
        tab_devices, tab_history = st.tabs(["📱 Devices", "📊 Login History"])
        
        with tab_devices:
            st.subheader("Registered Devices")
            
            devices_df = get_all_devices()
            
            if devices_df.empty:
                st.info("No devices registered yet")
            else:
                for idx, row in devices_df.iterrows():
                    with st.expander(
                        f"{'✅' if row['is_approved'] else '⏳'} {row['device_name']} - {row['ip_address']}",
                        expanded=False
                    ):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.caption(f"**Device ID:** `{row['device_id'][:20]}...`")
                            st.caption(f"**IP Address:** {row['ip_address']}")
                            st.caption(f"**First Login:** {row['first_login']}")
                            st.caption(f"**Last Login:** {row['last_login']}")
                            st.caption(f"**Session:** {row['session_status']}")
                            st.caption(f"**Status:** {'✅ Approved' if row['is_approved'] else '⏳ Pending'}")
                        
                        with col2:
                            if row['is_approved']:
                                if st.button("🚫 Revoke Access", key=f"revoke_{row['id']}"):
                                    revoke_device(row['device_id'])
                                    st.success("Access revoked!")
                                    st.rerun()
                            else:
                                if st.button("✅ Approve Device", key=f"approve_{row['id']}"):
                                    approve_device(row['device_id'])
                                    st.success("Device approved!")
                                    st.rerun()
                            
                            if st.button("🗑️ Delete Device", key=f"delete_{row['id']}", type="secondary"):
                                delete_device(row['device_id'])
                                st.success("Device deleted!")
                                st.rerun()
        
        with tab_history:
            st.subheader("Recent Login Attempts")
            
            history_df = get_login_history()
            
            if history_df.empty:
                st.info("No login history yet")
            else:
                st.dataframe(history_df, use_container_width=True, height=400)

def add_logout_button():
    """Add logout button to sidebar"""
    st.sidebar.divider()
    
    if st.sidebar.button("🚪 Logout", use_container_width=True, type="secondary"):
        # Clear session
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()



# ============================================================================
# NEW FUNCTION 1: Get Historical Efficiency Data
# ============================================================================
def get_efficiency_history():
    """Fetch daily task completion rates for all days with tasks"""
    conn = sqlite3.connect('study_tracker.db')
    
    query = """
    SELECT 
        date,
        COUNT(*) as total_tasks,
        SUM(is_completed) as completed_tasks,
        ROUND(CAST(SUM(is_completed) AS FLOAT) / COUNT(*) * 100, 1) as efficiency_percent
    FROM daily_tasks
    GROUP BY date
    ORDER BY date DESC
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # Convert date strings to datetime for better display
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df['day_name'] = df['date'].dt.strftime('%A')  # Monday, Tuesday, etc.
        df['display_date'] = df['date'].dt.strftime('%d %b %Y')  # 15 Dec 2024
    
    return df

# ============================================================================
# NEW FUNCTION 2: Create Beautiful Efficiency History Chart
# ============================================================================
def create_efficiency_timeline(history_df):
    """Create an interactive timeline chart of daily efficiency"""
    
    if history_df.empty:
        return None
    
    # Color coding based on efficiency
    colors = []
    for eff in history_df['efficiency_percent']:
        if eff >= 80:
            colors.append('#10b981')  # Green
        elif eff >= 60:
            colors.append('#f59e0b')  # Orange
        else:
            colors.append('#ef4444')  # Red
    
    fig = go.Figure()
    
    # Add bar chart
    fig.add_trace(go.Bar(
        x=history_df['display_date'],
        y=history_df['efficiency_percent'],
        marker_color=colors,
        text=history_df['efficiency_percent'].apply(lambda x: f"{x}%"),
        textposition='outside',
        hovertemplate=(
            '<b>%{x}</b><br>' +
            'Efficiency: %{y}%<br>' +
            'Completed: %{customdata[0]}/%{customdata[1]} tasks<br>' +
            '<extra></extra>'
        ),
        customdata=history_df[['completed_tasks', 'total_tasks']].values
    ))
    
    # Add target line at 80%
    fig.add_hline(
        y=80, 
        line_dash="dash", 
        line_color="green", 
        annotation_text="Target: 80%",
        annotation_position="right"
    )
    
    fig.update_layout(
        title={
            'text': "📊 Your Daily Efficiency Journey",
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 24, 'color': '#1f2937'}
        },
        xaxis_title="Date",
        yaxis_title="Efficiency %",
        yaxis=dict(range=[0, 110]),
        height=400,
        showlegend=False,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(size=12),
        margin=dict(l=50, r=50, t=80, b=50)
    )
    
    return fig

# ============================================================================
# NEW FUNCTION 3: Create Efficiency Calendar Heatmap
# ============================================================================
def create_efficiency_heatmap(history_df):
    """Create a calendar-style heatmap of efficiency"""
    
    if history_df.empty:
        return None
    
    # Prepare data for heatmap
    history_df['week'] = history_df['date'].dt.isocalendar().week
    history_df['weekday'] = history_df['date'].dt.dayofweek
    
    fig = px.density_heatmap(
        history_df,
        x='weekday',
        y='week',
        z='efficiency_percent',
        color_continuous_scale=['#ef4444', '#f59e0b', '#10b981'],
        labels={'efficiency_percent': 'Efficiency %'},
        range_color=[0, 100]
    )
    
    fig.update_layout(
        title="📅 Weekly Efficiency Heatmap",
        xaxis=dict(
            tickmode='array',
            tickvals=[0, 1, 2, 3, 4, 5, 6],
            ticktext=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        ),
        height=300
    )
    
    return fig

# ============================================================================
# NEW FUNCTION 4: Display Statistics Cards
# ============================================================================
def display_efficiency_stats(history_df):
    """Display beautiful stat cards with key metrics"""
    
    if history_df.empty:
        st.info("📊 No efficiency data yet. Start completing tasks!")
        return
    
    # Calculate statistics
    avg_efficiency = history_df['efficiency_percent'].mean()
    best_day = history_df.loc[history_df['efficiency_percent'].idxmax()]
    total_days = len(history_df)
    streak = calculate_streak(history_df)
    
    # Display in columns
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="📈 Average Efficiency",
            value=f"{avg_efficiency:.1f}%",
            delta=f"{avg_efficiency - 75:.1f}% vs target" if avg_efficiency < 75 else "Above target! 🎉"
        )
    
    with col2:
        st.metric(
            label="🏆 Best Day",
            value=f"{best_day['efficiency_percent']:.0f}%",
            delta=best_day['display_date']
        )
    
    with col3:
        st.metric(
            label="📅 Days Tracked",
            value=total_days,
            delta=f"{history_df['total_tasks'].sum()} total tasks"
        )
    
    with col4:
        st.metric(
            label="🔥 Current Streak",
            value=f"{streak} days",
            delta="Keep going!" if streak > 0 else "Start today!"
        )

def calculate_streak(history_df):
    """Calculate current streak of days with >50% efficiency"""
    if history_df.empty:
        return 0
    
    streak = 0
    for _, row in history_df.iterrows():
        if row['efficiency_percent'] >= 50:
            streak += 1
        else:
            break
    return streak

# ============================================================================
# PLACEMENT OPTION 1: IN TAB 1 (DAILY FOCUS) - BELOW TASKS
# ============================================================================
def placement_option_1_tab1():
    """Shows efficiency history in Daily Focus tab, below today's tasks"""
    
    st.divider()
    
    # Collapsible section with beautiful button
    with st.expander("📊 View Your Efficiency History", expanded=False):
        history_df = get_efficiency_history()
        
        if history_df.empty:
            st.info("🌟 Start completing tasks to see your efficiency journey!")
        else:
            # Stats cards at top
            display_efficiency_stats(history_df)
            
            st.divider()
            
            # Timeline chart
            fig = create_efficiency_timeline(history_df)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
            
            # Detailed table
            st.subheader("📋 Detailed History")
            
            # Format the dataframe for display
            display_df = history_df[['display_date', 'day_name', 'completed_tasks', 'total_tasks', 'efficiency_percent']].copy()
            display_df.columns = ['Date', 'Day', 'Completed', 'Total', 'Efficiency %']
            
            # Color code the efficiency column
            def highlight_efficiency(val):
                if val >= 80:
                    return 'background-color: #d1fae5; color: #065f46'
                elif val >= 60:
                    return 'background-color: #fef3c7; color: #92400e'
                else:
                    return 'background-color: #fee2e2; color: #991b1b'
            
            styled_df = display_df.style.applymap(
                highlight_efficiency, 
                subset=['Efficiency %']
            )
            
            st.dataframe(styled_df, use_container_width=True, height=300)

# ============================================================================
# PLACEMENT OPTION 2: SEPARATE TAB (NEW TAB 3)
# ============================================================================
def placement_option_2_new_tab():
    """Create a dedicated 'Analytics' tab for efficiency history"""
    
    st.header("📊 Efficiency Analytics Dashboard")
    
    history_df = get_efficiency_history()
    
    if history_df.empty:
        st.info("🌟 Start completing tasks to unlock your analytics dashboard!")
        st.image("https://via.placeholder.com/800x400/667eea/ffffff?text=Your+Analytics+Will+Appear+Here", 
                 use_container_width=True)
        return
    
    # Stats cards
    display_efficiency_stats(history_df)
    
    st.divider()
    
    # Two columns for charts
    col1, col2 = st.columns(2)
    
    with col1:
        # Timeline chart
        fig_timeline = create_efficiency_timeline(history_df)
        if fig_timeline:
            st.plotly_chart(fig_timeline, use_container_width=True)
    
    with col2:
        # Heatmap
        fig_heatmap = create_efficiency_heatmap(history_df)
        if fig_heatmap:
            st.plotly_chart(fig_heatmap, use_container_width=True)
    
    st.divider()
    
    # Insights section
    st.subheader("💡 AI-Powered Insights")
    
    avg_eff = history_df['efficiency_percent'].mean()
    best_day_name = history_df.loc[history_df['efficiency_percent'].idxmax(), 'day_name']
    
    col_insight1, col_insight2 = st.columns(2)
    
    with col_insight1:
        if avg_eff >= 75:
            st.success(f"🎉 Excellent! Your average efficiency is {avg_eff:.1f}%. You're crushing it!")
        elif avg_eff >= 60:
            st.warning(f"⚡ Good work! {avg_eff:.1f}% average. Aim for 80% to maximize results!")
        else:
            st.error(f"🎯 {avg_eff:.1f}% average. Let's work on building consistency!")
    
    with col_insight2:
        st.info(f"📅 Your best performances are on **{best_day_name}s**. Schedule important tasks then!")
    
    # Detailed table
    st.divider()
    st.subheader("📋 Complete History Table")
    
    display_df = history_df[['display_date', 'day_name', 'completed_tasks', 'total_tasks', 'efficiency_percent']].copy()
    display_df.columns = ['Date', 'Day', 'Completed', 'Total', 'Efficiency %']
    st.dataframe(display_df, use_container_width=True, height=400)

# ============================================================================
# PLACEMENT OPTION 3: IN SIDEBAR (COMPACT VIEW)
# ============================================================================
def placement_option_3_sidebar():
    """Compact efficiency history in sidebar"""
    
    with st.sidebar:
        st.divider()
        
        if st.button("📊 View Efficiency History", use_container_width=True, type="secondary"):
            st.session_state.show_efficiency_modal = True
        
        # Show last 7 days mini preview
        st.caption("📈 Last 7 Days")
        history_df = get_efficiency_history()
        
        if not history_df.empty:
            recent_7 = history_df.head(7)
            
            for _, row in recent_7.iterrows():
                eff = row['efficiency_percent']
                emoji = "🟢" if eff >= 80 else "🟡" if eff >= 60 else "🔴"
                st.caption(f"{emoji} {row['display_date']}: {eff}%")
        else:
            st.caption("No data yet")

# ============================================================================
# PLACEMENT OPTION 4: FLOATING BUTTON (BOTTOM RIGHT)
# ============================================================================
def placement_option_4_floating():
    """Add a floating action button for efficiency history"""
    
    # Custom CSS for floating button
    st.markdown("""
        <style>
        .floating-button {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 999;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 50px;
            padding: 15px 25px;
            font-size: 16px;
            font-weight: bold;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            cursor: pointer;
            transition: transform 0.2s;
        }
        .floating-button:hover {
            transform: scale(1.05);
        }
        </style>
    """, unsafe_allow_html=True)
    
    # Use session state to toggle modal
    if 'show_efficiency_modal' not in st.session_state:
        st.session_state.show_efficiency_modal = False
    
    # Button columns at bottom
    col1, col2, col3 = st.columns([8, 2, 1])
    with col2:
        if st.button("📊 History", use_container_width=True, type="primary"):
            st.session_state.show_efficiency_modal = not st.session_state.show_efficiency_modal

# ============================================================================
# MODAL/DIALOG FOR EFFICIENCY HISTORY
# ============================================================================
def show_efficiency_modal():
    """Display efficiency history in a modal-style container"""
    
    if st.session_state.get('show_efficiency_modal', False):
        with st.container():
            st.markdown("---")
            
            col_close1, col_title, col_close2 = st.columns([8, 2, 1])
            with col_title:
                st.subheader("📊 Efficiency History")
            with col_close2:
                if st.button("✖", key="close_modal"):
                    st.session_state.show_efficiency_modal = False
                    st.rerun()
            
            history_df = get_efficiency_history()
            
            if not history_df.empty:
                display_efficiency_stats(history_df)
                
                fig = create_efficiency_timeline(history_df)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                
                with st.expander("📋 View Detailed Table"):
                    display_df = history_df[['display_date', 'day_name', 'completed_tasks', 'total_tasks', 'efficiency_percent']].copy()
                    display_df.columns = ['Date', 'Day', 'Completed', 'Total', 'Efficiency %']
                    st.dataframe(display_df, use_container_width=True)
            else:
                st.info("No efficiency data available yet!")
            
            st.markdown("---")

# ============================================================================
# EXAMPLE USAGE IN YOUR MAIN APP
# ============================================================================

# In your Tab 1 (Daily Focus), add this at the end:
# placement_option_1_tab1()

# OR create a new Tab 3:
# tab1, tab2, tab3 = st.tabs(["📝 Daily Focus", "🎯 Master Plan", "📊 Analytics"])
# with tab3:
#     placement_option_2_new_tab()

# OR in sidebar:
# placement_option_3_sidebar()

# OR with floating button:
# placement_option_4_floating()
# show_efficiency_modal()

# Get database path in the same directory as the script
DB_PATH = os.path.join(os.path.dirname(__file__), 'study_tracker.db')

# Database Setup
def init_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Syllabus Tracker Table
    c.execute('''CREATE TABLE IF NOT EXISTS syllabus_tracker
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  phase TEXT,
                  subject TEXT,
                  chapter TEXT,
                  status TEXT DEFAULT 'Not Started')''')
    
    # Daily Tasks Table
    c.execute('''CREATE TABLE IF NOT EXISTS daily_tasks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  task_name TEXT,
                  date TEXT,
                  is_completed INTEGER DEFAULT 0)''')
    
    # Check if syllabus data exists
    c.execute("SELECT COUNT(*) FROM syllabus_tracker")
    if c.fetchone()[0] == 0:
        populate_syllabus(c)
    
    conn.commit()
    conn.close()

def populate_syllabus(cursor):
    syllabus_data = [
        # --- PHASE 1: BUILD + BOOST (Days 1-60) ---
    
    # Weeks 1-2 (Days 1-14): Foundation & Mechanics
    ("Phase 1 (Wk 1-2)", "Physics", "Units & Dimensions, Kinematics, NLM, Friction"),
    ("Phase 1 (Wk 1-2)", "Physics", "Work Energy Power, Circular Motion (Basics)"),
    ("Phase 1 (Wk 1-2)", "Chemistry", "Mole Concept, States of Matter, Thermodynamics"),
    ("Phase 1 (Wk 1-2)", "Chemistry", "Chemical Equilibrium, Ionic Equilibrium"),
    ("Phase 1 (Wk 1-2)", "Maths", "Quadratic Eq, Complex Numbers, Seq & Series"),
    ("Phase 1 (Wk 1-2)", "Maths", "Polynomials, Matrices, Determinants"),

    # Weeks 3-4 (Days 15-28): Organic Base, Waves & Coordinate
    ("Phase 1 (Wk 3-4)", "Physics", "COM, Rotational (Basics), Gravitation, SHM"),
    ("Phase 1 (Wk 3-4)", "Physics", "Waves, Doppler, Fluid Basics"),
    ("Phase 1 (Wk 3-4)", "Chemistry", "GOC, Isomerism, Hydrocarbons"),
    ("Phase 1 (Wk 3-4)", "Chemistry", "Alkyl Halides, Alcohols, Phenols, Ethers"),
    ("Phase 1 (Wk 3-4)", "Maths", "Trigonometry, PnC, Probability Basics"),
    ("Phase 1 (Wk 3-4)", "Maths", "Straight Lines, Circles, Parabola (Formulas only)"),

    # Week 5 (Days 29-35): High Yield Organic & Electrostatics
    ("Phase 1 (Wk 5)", "Physics", "Electrostatics (Field/Potential), Capacitance"),
    ("Phase 1 (Wk 5)", "Physics", "Current Electricity (Kirchhoff Basics)"),
    ("Phase 1 (Wk 5)", "Chemistry", "Aldehydes, Ketones, Carboxylic Acids"),
    ("Phase 1 (Wk 5)", "Chemistry", "Amines, Biomolecules, Polymers"),
    ("Phase 1 (Wk 5)", "Maths", "Vectors, 3D Geometry"),

    # Week 6 (Days 36-42): Inorganic Block 1 & Magnetism
    ("Phase 1 (Wk 6)", "Physics", "Magnetism, Moving Charges, EMI, AC"),
    ("Phase 1 (Wk 6)", "Chemistry", "Periodic Table, Bonding"),
    ("Phase 1 (Wk 6)", "Chemistry", "s-Block, p-Block (Imp NCERT lines)"),
    ("Phase 1 (Wk 6)", "Maths", "Calculus Base: Limits, Derivatives"),

    # Weeks 7-8 (Days 43-60): Inorganic Block 2, Optics & Modern
    ("Phase 1 (Wk 7-8)", "Physics", "Ray Optics, Optical Instruments"),
    ("Phase 1 (Wk 7-8)", "Physics", "Modern Physics, Semiconductors"),
    ("Phase 1 (Wk 7-8)", "Chemistry", "Coordination Compounds, d&f Block"),
    ("Phase 1 (Wk 7-8)", "Chemistry", "Hydrogen, Environmental Chem, Full NCERT Rev"),
    ("Phase 1 (Wk 7-8)", "Maths", "Calculus: AOD, Integration, Area Under Curve"),

    # --- PHASE 2: RUTHLESS REVISION (Days 61-80) ---
    ("Phase 2 (Days 61-80)", "Chemistry", "Full NCERT Rev + Exemplar + 5 PYQ Papers"),
    ("Phase 2 (Days 61-80)", "Physics", "7 Days Pure PYQs (Mech + Modern + Optics)"),
    ("Phase 2 (Days 61-80)", "Maths", "PYQ Focus (Algebra + Coordinate + Calculus)"),
    ("Phase 2 (Days 61-80)", "Mock Tests", "Mini Mocks (Target 100-120 Marks)"),

    # --- PHASE 3: MOCK TEST ATTACK (Days 81-110) ---
    ("Phase 3 (Days 81-110)", "Mocks", "15 Full Mocks (1 every 2 days)"),
    ("Phase 3 (Days 81-110)", "Analysis", "Error Notebook (Concept vs Silly Mistakes)"),
    ("Phase 3 (Days 81-110)", "Target", "Score Goal: 130 -> 145 -> 160+"),

    # --- PHASE 4: FINAL SHARPENING (Days 111-120) ---
    ("Phase 4 (Days 111-120)", "Revision", "All Formula Rev + NCERT Scan"),
    ("Phase 4 (Days 111-120)", "Mocks", "6 Mini Mocks (Accuracy Focus)"),
    ]
    
    cursor.executemany('''INSERT INTO syllabus_tracker 
                         (phase, subject, chapter) 
                         VALUES (?, ?, ?)''', syllabus_data)

# Database Operations
def add_daily_task(task_name, task_date):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO daily_tasks (task_name, date, is_completed) VALUES (?, ?, 0)",
              (task_name, task_date))
    conn.commit()
    conn.close()

def get_daily_tasks(task_date):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT * FROM daily_tasks WHERE date = ? ORDER BY id",
        conn, params=(task_date,))
    conn.close()
    return df

def update_task_status(task_id, is_completed):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE daily_tasks SET is_completed = ? WHERE id = ?",
              (1 if is_completed else 0, task_id))
    conn.commit()
    conn.close()

def delete_task(task_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM daily_tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

def get_syllabus_data():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM syllabus_tracker ORDER BY id", conn)
    conn.close()
    return df

def update_syllabus_status(chapter_id, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE syllabus_tracker SET status = ? WHERE id = ?",
              (status, chapter_id))
    conn.commit()
    conn.close()

def get_completion_stats():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT phase, 
               COUNT(*) as total,
               SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed
        FROM syllabus_tracker 
        GROUP BY phase
    """, conn)
    conn.close()
    return df

# Visualization Functions
def create_daily_progress_chart(completed, total):
    if total == 0:
        return None
    
    percentage = (completed / total) * 100
    
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=percentage,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': "Today's Efficiency", 'font': {'size': 24}},
        delta={'reference': 100, 'increasing': {'color': "green"}},
        gauge={
            'axis': {'range': [None, 100], 'tickwidth': 1, 'tickcolor': "darkblue"},
            'bar': {'color': "darkgreen"},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [0, 50], 'color': '#ffcccc'},
                {'range': [50, 75], 'color': '#ffffcc'},
                {'range': [75, 100], 'color': '#ccffcc'}],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 90}}))
    
    fig.update_layout(height=300, margin=dict(l=20, r=20, t=50, b=20))
    return fig

def create_phase_progress_chart(stats_df):
    fig = go.Figure()
    
    for _, row in stats_df.iterrows():
        percentage = (row['completed'] / row['total']) * 100 if row['total'] > 0 else 0
        fig.add_trace(go.Bar(
            name=f"Phase {row['phase']}",
            x=[row['phase']],
            y=[percentage],
            text=[f"{row['completed']}/{row['total']}"],
            textposition='auto',
        ))
    
    fig.update_layout(
        title="Long-Term Progress by Phase",
        xaxis_title="Phase",
        yaxis_title="Completion %",
        yaxis=dict(range=[0, 100]),
        height=300,
        showlegend=False,
        margin=dict(l=20, r=20, t=50, b=20)
    )
    
    return fig

def calculate_projected_score(stats_df):
    total_items = stats_df['total'].sum()
    completed_items = stats_df['completed'].sum()
    
    if total_items == 0:
        return "Start your journey!", "0%"
    
    overall_percentage = (completed_items / total_items) * 100
    
    phase_a = stats_df[stats_df['phase'] == 'A']['completed'].sum()
    phase_b = stats_df[stats_df['phase'] == 'B']['completed'].sum()
    phase_c = stats_df[stats_df['phase'] == 'C']['completed'].sum()
    phase_d = stats_df[stats_df['phase'] == 'D']['completed'].sum()
    
    phase_a_total = stats_df[stats_df['phase'] == 'A']['total'].sum()
    phase_b_total = stats_df[stats_df['phase'] == 'B']['total'].sum()
    phase_c_total = stats_df[stats_df['phase'] == 'C']['total'].sum()
    phase_d_total = stats_df[stats_df['phase'] == 'D']['total'].sum()
    
    if phase_d > phase_d_total * 0.7:
        return "Projected: 120-150 Marks", f"{overall_percentage:.1f}%"
    elif phase_c > phase_c_total * 0.7:
        return "Projected: 95-125 Marks", f"{overall_percentage:.1f}%"
    elif phase_b > phase_b_total * 0.7:
        return "Projected: 80-100 Marks", f"{overall_percentage:.1f}%"
    elif phase_a > phase_a_total * 0.7:
        return "Projected: 50-70 Marks", f"{overall_percentage:.1f}%"
    else:
        return "Projected: 20-50 Marks", f"{overall_percentage:.1f}%"

# Initialize Database
init_database()

# Main Application
st.title("📚 Daily Efficiency Tracker")

# Sidebar - Progress Overview
with st.sidebar:
    st.header("📊 Progress Overview")
    
    stats_df = get_completion_stats()
    projected_score, completion_pct = calculate_projected_score(stats_df)
    
    st.metric("Overall Completion", completion_pct)
    st.metric("Projected JEE Score", projected_score)
    
    st.divider()
    
    if not stats_df.empty:
        fig = create_phase_progress_chart(stats_df)
        st.plotly_chart(fig, width='stretch')
    
    st.divider()
    st.caption("💡 Tip: Complete Phase A for strong foundations!")
    
    # 👇👇👇 NEW CODE STARTS HERE 👇👇👇
    
    # Efficiency Preview (Last 7 Days)
    st.divider()
    st.caption("📈 Last 7 Days Preview")
    
    history_df = get_efficiency_history()
    
    if not history_df.empty:
        recent_7 = history_df.head(7)
        
        for _, row in recent_7.iterrows():
            eff = row['efficiency_percent']
            emoji = "🟢" if eff >= 80 else "🟡" if eff >= 60 else "🔴"
            st.caption(f"{emoji} {row['display_date']}: {eff}%")
    else:
        st.caption("No efficiency data yet. Start tracking!")
    
    # Admin Panel and Logout Buttons
    show_admin_panel()
    add_logout_button()
    
    # 👆👆👆 NEW CODE ENDS HERE 👆👆👆

# Main Tabs
tab1, tab2, tab3 = st.tabs(["📝 Daily Focus", "🎯 The Master Plan", "📊 Analytics"])

# Tab 1: Daily Focus
with tab1:
    st.header("Today's Battle Plan")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        today = date.today().isoformat()
        
        # Add Task Section
        st.subheader("➕ Add New Task")
        new_task = st.text_input("Task Description", placeholder="e.g., Solve 20 PYQs on Kinematics")
        
        col_btn1, col_btn2 = st.columns([1, 4])
        with col_btn1:
            if st.button("Add Task", type="primary"):
                if new_task:
                    add_daily_task(new_task, today)
                    st.success("Task added!")
                    st.rerun()
                else:
                    st.warning("Please enter a task description")
        
        st.divider()
        
        # Display Tasks
        st.subheader("✅ Today's Tasks")
        tasks_df = get_daily_tasks(today)
        
        if tasks_df.empty:
            st.info("No tasks for today. Add your first task above!")
        else:
            for idx, row in tasks_df.iterrows():
                col_check, col_task, col_delete = st.columns([1, 8, 1])
                
                with col_check:
                    checked = st.checkbox(
                        "Done",
                        value=bool(row['is_completed']),
                        key=f"task_{row['id']}",
                        label_visibility="collapsed"
                    )
                    if checked != bool(row['is_completed']):
                        update_task_status(row['id'], checked)
                        st.rerun()
                
                with col_task:
                    if row['is_completed']:
                        st.markdown(f"~~{row['task_name']}~~")
                    else:
                        st.markdown(f"{row['task_name']}")
                
                with col_delete:
                    if st.button("🗑️", key=f"del_{row['id']}"):
                        delete_task(row['id'])
                        st.rerun()
    
    with col2:
        st.subheader("📈 Daily Efficiency")
        
        tasks_df = get_daily_tasks(today)
        if not tasks_df.empty:
            completed = tasks_df['is_completed'].sum()
            total = len(tasks_df)
            
            fig = create_daily_progress_chart(completed, total)
            if fig:
                st.plotly_chart(fig, width='stretch')
            
            st.metric("Tasks Completed", f"{completed}/{total}")
        else:
            st.info("Add tasks to see your daily efficiency!")

# Tab 2: Master Plan
with tab2:
    st.header("🎯 120-Day Syllabus Roadmap")
    
    syllabus_df = get_syllabus_data()
    
    # Phase Selection
    phases = syllabus_df['phase'].unique()
    selected_phase = st.selectbox("Select Phase", phases)
    
    phase_data = syllabus_df[syllabus_df['phase'] == selected_phase]
    
    # Group by subject
    subjects = phase_data['subject'].unique()
    
    for subject in subjects:
        with st.expander(f"📚 {subject}", expanded=True):
            subject_data = phase_data[phase_data['subject'] == subject]
            
            for _, row in subject_data.iterrows():
                col_status, col_chapter = st.columns([1, 4])
                
                with col_status:
                    status_options = ['Not Started', 'In Progress', 'Completed']
                    current_status = row['status']
                    new_status = st.selectbox(
                        "Status",
                        status_options,
                        index=status_options.index(current_status),
                        key=f"status_{row['id']}",
                        label_visibility="collapsed"
                    )
                    
                    if new_status != current_status:
                        update_syllabus_status(row['id'], new_status)
                        st.rerun()
                
                with col_chapter:
                    status_emoji = {
                        'Not Started': '⚪',
                        'In Progress': '🟡',
                        'Completed': '🟢'
                    }
                    st.markdown(f"{status_emoji[new_status]} {row['chapter']}")
# Tab 3: Analytics Dashboard
with tab3:
    st.header("📊 Efficiency Analytics Dashboard")
    
    history_df = get_efficiency_history()
    
    if history_df.empty:
        st.info("🌟 Start completing tasks to unlock your analytics dashboard!")
        st.image("https://via.placeholder.com/800x400/667eea/ffffff?text=Your+Analytics+Will+Appear+Here", 
                 use_container_width=True)
    else:
        # Stats cards
        display_efficiency_stats(history_df)
        
        st.divider()
        
        # Two columns for charts
        col1, col2 = st.columns(2)
        
        with col1:
            fig_timeline = create_efficiency_timeline(history_df)
            if fig_timeline:
                st.plotly_chart(fig_timeline, use_container_width=True)
        
        with col2:
            fig_heatmap = create_efficiency_heatmap(history_df)
            if fig_heatmap:
                st.plotly_chart(fig_heatmap, use_container_width=True)
        
        st.divider()
        
        # Insights section
        st.subheader("💡 AI-Powered Insights")
        
        avg_eff = history_df['efficiency_percent'].mean()
        best_day_name = history_df.loc[history_df['efficiency_percent'].idxmax(), 'day_name']
        
        col_insight1, col_insight2 = st.columns(2)
        
        with col_insight1:
            if avg_eff >= 75:
                st.success(f"🎉 Excellent! Your average efficiency is {avg_eff:.1f}%. You're crushing it!")
            elif avg_eff >= 60:
                st.warning(f"⚡ Good work! {avg_eff:.1f}% average. Aim for 80% to maximize results!")
            else:
                st.error(f"🎯 {avg_eff:.1f}% average. Let's work on building consistency!")
        
        with col_insight2:
            st.info(f"📅 Your best performances are on **{best_day_name}s**. Schedule important tasks then!")
        
        # Detailed table
        st.divider()
        st.subheader("📋 Complete History Table")
        
        display_df = history_df[['display_date', 'day_name', 'completed_tasks', 'total_tasks', 'efficiency_percent']].copy()
        display_df.columns = ['Date', 'Day', 'Completed', 'Total', 'Efficiency %']
        st.dataframe(display_df, use_container_width=True, height=400)
# Footer
st.divider()

st.caption("🚀 Consistency is the key to JEE success. Track daily, win big!")





