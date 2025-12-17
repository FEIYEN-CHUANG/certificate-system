#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
課程管理通知系統 - Streamlit 網頁版 v2
自動讀取 Secrets，不需每次登入
"""

import streamlit as st
import pandas as pd
import json
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
import io

# ==================== 頁面設定 ====================
st.set_page_config(
    page_title="課程管理通知系統",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 自訂 CSS ====================
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: bold;
        color: #2C3E50;
        text-align: center;
        padding: 1rem;
        border-bottom: 3px solid #3498DB;
        margin-bottom: 1.5rem;
    }
    .sub-header {
        font-size: 1.4rem;
        color: #34495E;
        border-left: 4px solid #3498DB;
        padding-left: 1rem;
        margin: 1.5rem 0;
    }
    .company-name {
        font-size: 1rem;
        color: #7f8c8d;
        text-align: center;
        margin-bottom: 1rem;
    }
    .success-box {
        background-color: #D4EDDA;
        border: 1px solid #C3E6CB;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .warning-box {
        background-color: #FFF3CD;
        border: 1px solid #FFEEBA;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .info-box {
        background-color: #D1ECF1;
        border: 1px solid #BEE5EB;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .error-box {
        background-color: #F8D7DA;
        border: 1px solid #F5C6CB;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .stButton > button {
        width: 100%;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
        padding: 1rem;
        color: white;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ==================== 標準欄位定義 ====================
STANDARD_COLUMNS = [
    '項次', '查詢序號', '報名時間', 'IP位址', '姓名',
    '出生年', '月', '日', '身分證字號', '學歷',
    '縣市', '郵遞區號', '地址', '行動電話',
    'Email', '公司名稱', '統一編號', '職稱',
    '前次回訓日期', '證照到期日', '報名狀態', '回覆時間'
]

# ==================== 預設設定 ====================
DEFAULT_CONFIG = {
    'company_name': '台灣安全衛生協會苗栗職業訓練中心',
    'notification_days': [30, 15, 7, -30],
    'gmail_account': '',
    'gmail_password': '',
    'sender_name': '',
    'sender_phone': ''
}

# ==================== 讀取設定 ====================
def get_config():
    """從 Streamlit Secrets 或預設值讀取設定"""
    config = DEFAULT_CONFIG.copy()
    
    try:
        # 嘗試從 Streamlit Secrets 讀取
        if hasattr(st, 'secrets'):
            if 'gmail' in st.secrets:
                config['gmail_account'] = st.secrets['gmail'].get('account', '')
                config['gmail_password'] = st.secrets['gmail'].get('password', '')
                config['company_name'] = st.secrets['gmail'].get('company_name', config['company_name'])
            
            if 'user' in st.secrets:
                config['sender_name'] = st.secrets['user'].get('name', '')
                config['sender_phone'] = st.secrets['user'].get('phone', '')
            
            if 'settings' in st.secrets:
                notification_days = st.secrets['settings'].get('notification_days', None)
                if notification_days:
                    config['notification_days'] = list(notification_days)
    except Exception as e:
        st.warning(f"讀取設定時發生錯誤：{e}")
    
    return config

# ==================== Session State 初始化 ====================
def init_session_state():
    """初始化 session state"""
    if 'initialized' not in st.session_state:
        st.session_state.initialized = True
        st.session_state.config = get_config()
        st.session_state.current_df = None
        st.session_state.current_file_name = None
        st.session_state.column_mapping = {}
        st.session_state.sent_records = {}
        st.session_state.page = 'home'
        st.session_state.gmail_verified = False

init_session_state()

# ==================== 輔助函數 ====================

def parse_roc_date(roc_date_str):
    """將民國年日期字串轉換為 datetime 物件"""
    if not roc_date_str or str(roc_date_str) == 'nan':
        return None
    
    roc_date_str = str(roc_date_str).strip()
    
    match = re.match(r'(\d{2,3})年(\d{1,2})月(\d{1,2})日?', roc_date_str)
    if match:
        roc_year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        west_year = roc_year + 1911
        
        try:
            return datetime(west_year, month, day)
        except ValueError:
            return None
    
    return None


def format_date_to_roc(date_obj):
    """將 datetime 物件轉換為民國年格式字串"""
    if not date_obj:
        return ''
    
    if isinstance(date_obj, str):
        if '年' in date_obj:
            return date_obj
        try:
            date_obj = datetime.strptime(date_obj, '%Y-%m-%d')
        except:
            return date_obj
    
    roc_year = date_obj.year - 1911
    return f"{roc_year}年{date_obj.month}月{date_obj.day}日"


def calculate_days_until_expiry(expire_date_str):
    """計算距離到期日的天數"""
    if not expire_date_str or str(expire_date_str) == 'nan':
        return None
    
    if isinstance(expire_date_str, str):
        if '年' in expire_date_str:
            expire_date = parse_roc_date(expire_date_str)
        else:
            try:
                expire_date = datetime.strptime(expire_date_str, '%Y-%m-%d')
            except:
                return None
    else:
        expire_date = expire_date_str
    
    if not expire_date:
        return None
    
    today = datetime.now()
    delta = expire_date - today
    return delta.days


def standardize_dataframe(df):
    """標準化 DataFrame 欄位名稱"""
    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = ''
    
    existing_cols = [col for col in STANDARD_COLUMNS if col in df.columns]
    other_cols = [col for col in df.columns if col not in STANDARD_COLUMNS]
    df = df[existing_cols + other_cols]
    
    return df


def smart_column_mapping(df_columns):
    """智慧欄位對應建議"""
    suggestions = {}
    
    mapping_rules = {
        '姓名': ['姓名', 'name', '學員姓名', '學生姓名'],
        'Email': ['email', 'e-mail', '電子郵件', '信箱', 'mail'],
        '證照到期日': ['證照到期日', '證書到期日', '到期日', '有效期限'],
        '前次回訓日期': ['前次回訓', '回訓時間', '回訓日期', '上課日期', '訓練日期'],
        '報名狀態': ['報名狀態', '狀態', '回覆狀態'],
        '回覆時間': ['回覆時間', '回信時間'],
        '公司名稱': ['公司名稱', '公司', '服務單位', '單位'],
        '行動電話': ['行動電話', '電話', '手機', 'phone', 'tel']
    }
    
    for sys_col, keywords in mapping_rules.items():
        for excel_col in df_columns:
            excel_col_lower = str(excel_col).lower()
            for keyword in keywords:
                if keyword.lower() in excel_col_lower:
                    suggestions[sys_col] = excel_col
                    break
            if sys_col in suggestions:
                break
    
    return suggestions


def test_gmail_connection(gmail_account, gmail_password):
    """測試 Gmail 連線"""
    if not gmail_account or not gmail_password:
        return False, "尚未設定 Gmail 帳號或密碼"
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(gmail_account, gmail_password)
        server.quit()
        return True, "連線成功！"
    except smtplib.SMTPAuthenticationError:
        return False, "登入失敗！請確認帳號和應用程式密碼是否正確"
    except Exception as e:
        return False, f"連線失敗：{str(e)}"


def send_email(to_email, subject, content, config, attachments=None):
    """發送郵件"""
    try:
        gmail_account = config['gmail_account']
        gmail_password = config['gmail_password']
        
        if not gmail_account or not gmail_password:
            return False, "尚未設定 Gmail 帳號或密碼"
        
        msg = MIMEMultipart()
        msg['From'] = gmail_account
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # 加入簽名
        signature = "\n\n---\n"
        if config.get('company_name'):
            signature += f"{config['company_name']}\n"
        if config.get('sender_name'):
            signature += f"承辦人：{config['sender_name']}\n"
        if config.get('sender_phone'):
            signature += f"聯絡電話：{config['sender_phone']}\n"
        
        full_content = content + signature
        msg.attach(MIMEText(full_content, 'plain', 'utf-8'))
        
        # 附件處理
        if attachments:
            for file_data, file_name in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(file_data)
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=('utf-8', '', file_name)
                )
                msg.attach(part)
        
        # 發送
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(gmail_account, gmail_password)
        server.send_message(msg)
        server.quit()
        
        return True, "發送成功"
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail 登入失敗，請檢查應用程式密碼"
    except Exception as e:
        return False, str(e)


def get_expiry_stage(days):
    """判斷到期階段"""
    if days is None:
        return None, "無資料", "gray"
    elif days < 0:
        return "expired", f"已過期 {abs(days)} 天", "🔴"
    elif days <= 7:
        return "urgent", f"剩餘 {days} 天（緊急）", "🔴"
    elif days <= 15:
        return "warning", f"剩餘 {days} 天（警告）", "🟠"
    elif days <= 30:
        return "notice", f"剩餘 {days} 天（提醒）", "🟡"
    else:
        return "normal", f"剩餘 {days} 天", "🟢"


def get_notification_stage_name(days, notification_days):
    """根據天數取得通知階段名稱"""
    if days is None:
        return "無法判斷"
    
    for stage_days in sorted(notification_days, reverse=True):
        if stage_days > 0 and days <= stage_days:
            return f"{stage_days}天前通知"
        elif stage_days < 0 and days < 0 and days >= stage_days:
            return f"過期{abs(stage_days)}天內通知"
    
    return "不在通知範圍"


# ==================== 頁面函數 ====================

def show_sidebar():
    """顯示側邊欄"""
    with st.sidebar:
        config = st.session_state.config
        
        st.markdown(f"### 🎓 課程管理通知系統")
        st.markdown(f"<small>{config['company_name']}</small>", unsafe_allow_html=True)
        st.markdown("---")
        
        # Gmail 連線狀態
        if config['gmail_account']:
            if st.session_state.gmail_verified:
                st.success(f"✅ {config['gmail_account']}")
            else:
                st.warning(f"⚠️ {config['gmail_account']}")
                if st.button("🔌 測試連線", key="test_conn_sidebar"):
                    with st.spinner("測試中..."):
                        success, msg = test_gmail_connection(
                            config['gmail_account'],
                            config['gmail_password']
                        )
                    if success:
                        st.session_state.gmail_verified = True
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.error("❌ 尚未設定 Gmail")
        
        st.markdown("---")
        
        # 導航按鈕
        if st.button("🏠 首頁", use_container_width=True):
            st.session_state.page = 'home'
            st.rerun()
        
        if st.button("📁 課程管理", use_container_width=True):
            st.session_state.page = 'course'
            st.rerun()
        
        if st.button("👥 學員名單", use_container_width=True):
            st.session_state.page = 'students'
            st.rerun()
        
        if st.button("📧 發送通知", use_container_width=True):
            st.session_state.page = 'send'
            st.rerun()
        
        if st.button("📊 發送記錄", use_container_width=True):
            st.session_state.page = 'records'
            st.rerun()
        
        if st.button("⚙️ 設定", use_container_width=True):
            st.session_state.page = 'settings'
            st.rerun()


def show_home_page():
    """顯示首頁"""
    config = st.session_state.config
    
    st.markdown(f'<div class="main-header">🎓 課程管理通知系統</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="company-name">{config["company_name"]}</div>', unsafe_allow_html=True)
    
    # Gmail 設定檢查
    if not config['gmail_account'] or not config['gmail_password']:
        st.markdown("""
        <div class="error-box">
        <h4>⚠️ 尚未設定 Gmail</h4>
        <p>請到「⚙️ 設定」頁面設定 Gmail 帳號和應用程式密碼，或請管理員在 Streamlit Secrets 中設定。</p>
        </div>
        """, unsafe_allow_html=True)
    
    # 快速統計
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📁 載入課程", "1" if st.session_state.current_df is not None else "0")
    
    with col2:
        if st.session_state.current_df is not None:
            st.metric("👥 學員人數", len(st.session_state.current_df))
        else:
            st.metric("👥 學員人數", "0")
    
    with col3:
        total_sent = sum(len(v) for v in st.session_state.sent_records.values())
        st.metric("📧 已發送通知", total_sent)
    
    with col4:
        if st.session_state.current_df is not None and '報名狀態' in st.session_state.current_df.columns:
            registered = len(st.session_state.current_df[st.session_state.current_df['報名狀態'] == '已報名'])
            st.metric("✅ 已報名", registered)
        else:
            st.metric("✅ 已報名", "0")
    
    st.markdown("---")
    
    # 快速操作
    st.markdown('<div class="sub-header">🚀 快速開始</div>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        <div class="info-box">
        <h4>📁 步驟 1：載入課程</h4>
        <p>上傳學員名單 Excel 檔案</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("前往課程管理 →", key="goto_course"):
            st.session_state.page = 'course'
            st.rerun()
    
    with col2:
        st.markdown("""
        <div class="info-box">
        <h4>👥 步驟 2：檢視學員</h4>
        <p>確認學員資料與到期狀態</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("前往學員名單 →", key="goto_students"):
            st.session_state.page = 'students'
            st.rerun()
    
    with col3:
        st.markdown("""
        <div class="info-box">
        <h4>📧 步驟 3：發送通知</h4>
        <p>選擇學員並發送郵件通知</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("前往發送通知 →", key="goto_send"):
            st.session_state.page = 'send'
            st.rerun()
    
    # 通知規則說明
    st.markdown("---")
    st.markdown('<div class="sub-header">📋 通知規則</div>', unsafe_allow_html=True)
    
    notification_days = config['notification_days']
    cols = st.columns(len(notification_days))
    
    for i, days in enumerate(notification_days):
        with cols[i]:
            if days > 0:
                st.info(f"📅 到期前 **{days}** 天")
            else:
                st.warning(f"⚠️ 過期後 **{abs(days)}** 天內")


def show_course_page():
    """顯示課程管理頁面"""
    st.markdown('<div class="sub-header">📁 課程管理</div>', unsafe_allow_html=True)
    
    # 上傳檔案
    st.markdown("### 📤 上傳學員名單")
    
    uploaded_file = st.file_uploader(
        "選擇 Excel 檔案",
        type=['xlsx', 'xls'],
        help="支援 .xlsx 和 .xls 格式"
    )
    
    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            st.session_state.current_df = df
            st.session_state.current_file_name = uploaded_file.name
            
            st.success(f"✅ 已載入：{uploaded_file.name}（共 {len(df)} 筆資料）")
            
            # 顯示預覽
            st.markdown("### 📋 資料預覽")
            st.dataframe(df.head(10), use_container_width=True)
            
            # 欄位對應
            st.markdown("### 🔄 欄位對應")
            st.info("請確認 Excel 欄位與系統欄位的對應關係")
            
            suggestions = smart_column_mapping(df.columns)
            
            col1, col2 = st.columns(2)
            mapping = {}
            
            required_cols = ['姓名', 'Email', '證照到期日', '報名狀態']
            
            with col1:
                for sys_col in required_cols[:2]:
                    default = suggestions.get(sys_col, '')
                    options_list = [''] + list(df.columns)
                    default_idx = options_list.index(default) if default in options_list else 0
                    
                    mapping[sys_col] = st.selectbox(
                        f"{sys_col} {'*' if sys_col in ['姓名', 'Email'] else ''}",
                        options=options_list,
                        index=default_idx,
                        key=f"map_{sys_col}"
                    )
            
            with col2:
                for sys_col in required_cols[2:]:
                    default = suggestions.get(sys_col, '')
                    options_list = [''] + list(df.columns)
                    default_idx = options_list.index(default) if default in options_list else 0
                    
                    mapping[sys_col] = st.selectbox(
                        sys_col,
                        options=options_list,
                        index=default_idx,
                        key=f"map_{sys_col}"
                    )
            
            if st.button("✅ 套用欄位對應", use_container_width=True):
                if not mapping.get('姓名') or not mapping.get('Email'):
                    st.error("請至少設定「姓名」和「Email」欄位！")
                else:
                    # 套用對應
                    new_df = df.copy()
                    for sys_col, excel_col in mapping.items():
                        if excel_col and excel_col in df.columns:
                            new_df[sys_col] = df[excel_col]
                    
                    new_df = standardize_dataframe(new_df)
                    st.session_state.current_df = new_df
                    st.session_state.column_mapping = mapping
                    st.success("✅ 欄位對應已套用！")
                    st.rerun()
        
        except Exception as e:
            st.error(f"❌ 讀取檔案失敗：{str(e)}")
    
    # 顯示目前載入的課程
    if st.session_state.current_df is not None:
        st.markdown("---")
        st.markdown("### 📊 目前載入的課程")
        st.info(f"📁 {st.session_state.current_file_name}（{len(st.session_state.current_df)} 筆資料）")
        
        # 下載處理後的檔案
        buffer = io.BytesIO()
        st.session_state.current_df.to_excel(buffer, index=False, engine='openpyxl')
        buffer.seek(0)
        
        st.download_button(
            label="📥 下載處理後的 Excel",
            data=buffer,
            file_name=f"processed_{st.session_state.current_file_name}",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


def show_students_page():
    """顯示學員名單頁面"""
    st.markdown('<div class="sub-header">👥 學員名單</div>', unsafe_allow_html=True)
    
    if st.session_state.current_df is None:
        st.warning("⚠️ 請先在「課程管理」中載入學員名單")
        return
    
    df = st.session_state.current_df
    config = st.session_state.config
    
    # 統計資訊
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("總人數", len(df))
    
    with col2:
        if '報名狀態' in df.columns:
            registered = len(df[df['報名狀態'] == '已報名'])
            st.metric("✅ 已報名", registered)
        else:
            st.metric("✅ 已報名", "-")
    
    with col3:
        if '報名狀態' in df.columns:
            not_registered = len(df[df['報名狀態'] == '不報名'])
            st.metric("❌ 不報名", not_registered)
        else:
            st.metric("❌ 不報名", "-")
    
    with col4:
        if '報名狀態' in df.columns:
            next_time = len(df[df['報名狀態'] == '下期再通知'])
            st.metric("🔔 下期通知", next_time)
        else:
            st.metric("🔔 下期通知", "-")
    
    with col5:
        if '證照到期日' in df.columns:
            expired = 0
            for idx, row in df.iterrows():
                days = calculate_days_until_expiry(row.get('證照到期日', ''))
                if days is not None and days < 0:
                    expired += 1
            st.metric("🔴 已過期", expired)
        else:
            st.metric("🔴 已過期", "-")
    
    st.markdown("---")
    
    # 篩選功能
    col1, col2, col3 = st.columns(3)
    
    with col1:
        search_name = st.text_input("🔍 搜尋姓名", "")
    
    with col2:
        if '報名狀態' in df.columns:
            status_filter = st.selectbox(
                "📋 篩選狀態",
                options=['全部', '已報名', '不報名', '下期再通知', '未回覆']
            )
        else:
            status_filter = '全部'
    
    with col3:
        expiry_filter = st.selectbox(
            "📅 篩選到期",
            options=['全部', '已過期', '7天內到期', '15天內到期', '30天內到期']
        )
    
    # 套用篩選
    filtered_df = df.copy()
    
    if search_name:
        filtered_df = filtered_df[filtered_df['姓名'].astype(str).str.contains(search_name, na=False)]
    
    if status_filter != '全部' and '報名狀態' in filtered_df.columns:
        if status_filter == '未回覆':
            filtered_df = filtered_df[
                (filtered_df['報名狀態'].isna()) | (filtered_df['報名狀態'] == '')
            ]
        else:
            filtered_df = filtered_df[filtered_df['報名狀態'] == status_filter]
    
    if expiry_filter != '全部' and '證照到期日' in filtered_df.columns:
        def filter_by_expiry(row):
            days = calculate_days_until_expiry(row.get('證照到期日', ''))
            if days is None:
                return False
            if expiry_filter == '已過期':
                return days < 0
            elif expiry_filter == '7天內到期':
                return 0 <= days <= 7
            elif expiry_filter == '15天內到期':
                return 0 <= days <= 15
            elif expiry_filter == '30天內到期':
                return 0 <= days <= 30
            return True
        
        filtered_df = filtered_df[filtered_df.apply(filter_by_expiry, axis=1)]
    
    st.markdown(f"### 📋 學員列表（顯示 {len(filtered_df)} 筆）")
    
    # 顯示表格
    display_cols = ['姓名', 'Email', '證照到期日', '報名狀態', '公司名稱', '行動電話']
    display_cols = [col for col in display_cols if col in filtered_df.columns]
    
    # 加入到期狀態
    if '證照到期日' in filtered_df.columns:
        filtered_df = filtered_df.copy()
        filtered_df['到期狀態'] = filtered_df['證照到期日'].apply(
            lambda x: get_expiry_stage(calculate_days_until_expiry(x))[1]
        )
        if '到期狀態' not in display_cols:
            idx = display_cols.index('證照到期日') + 1 if '證照到期日' in display_cols else len(display_cols)
            display_cols.insert(idx, '到期狀態')
    
    st.dataframe(
        filtered_df[display_cols],
        use_container_width=True,
        height=400
    )


def show_send_page():
    """顯示發送通知頁面"""
    st.markdown('<div class="sub-header">📧 發送通知</div>', unsafe_allow_html=True)
    
    config = st.session_state.config
    
    # 檢查 Gmail 設定
    if not config['gmail_account'] or not config['gmail_password']:
        st.error("❌ 尚未設定 Gmail 帳號或密碼，請先到「設定」頁面設定")
        return
    
    if st.session_state.current_df is None:
        st.warning("⚠️ 請先在「課程管理」中載入學員名單")
        return
    
    df = st.session_state.current_df
    
    # 發送模式選擇
    send_mode = st.radio(
        "選擇發送模式",
        options=['🔔 到期通知', '📣 統一公告'],
        horizontal=True
    )
    
    st.markdown("---")
    
    if send_mode == '🔔 到期通知':
        show_expiry_notification(df, config)
    else:
        show_broadcast_notification(df, config)


def show_expiry_notification(df, config):
    """顯示到期通知發送介面"""
    st.markdown("### 🔔 到期通知")
    
    notification_days = config['notification_days']
    max_days = max([d for d in notification_days if d > 0], default=30)
    
    # 篩選條件
    col1, col2 = st.columns(2)
    
    with col1:
        days_before = st.number_input(
            "發送對象：到期日在幾天內的學員",
            min_value=1,
            max_value=365,
            value=max_days
        )
    
    with col2:
        include_expired = st.checkbox("包含已過期的學員", value=True)
        skip_sent = st.checkbox("跳過已發送過的學員", value=True)
    
    # 篩選學員
    eligible_students = []
    
    for idx, row in df.iterrows():
        name = str(row.get('姓名', '')).strip()
        email = str(row.get('Email', '')).strip()
        expire_date = row.get('證照到期日', '')
        status = str(row.get('報名狀態', '')).strip()
        
        # 基本檢查
        if not name or not email or '@' not in email:
            continue
        
        # 跳過已報名/不報名
        if status in ['已報名', '不報名']:
            continue
        
        # 計算到期天數
        days = calculate_days_until_expiry(expire_date)
        if days is None:
            continue
        
        # 檢查是否在範圍內
        if days <= days_before:
            if days < 0 and not include_expired:
                continue
            
            # 檢查是否已發送
            if skip_sent:
                record_key = f"{name}_{email}"
                file_records = st.session_state.sent_records.get(st.session_state.current_file_name, {})
                if record_key in file_records:
                    continue
            
            stage_name = get_notification_stage_name(days, notification_days)
            _, status_text, status_icon = get_expiry_stage(days)
            
            eligible_students.append({
                'idx': idx,
                'name': name,
                'email': email,
                'expire_date': expire_date,
                'days': days,
                'status_icon': status_icon,
                'status_text': status_text,
                'stage': stage_name,
                'company': str(row.get('公司名稱', '')) if pd.notna(row.get('公司名稱')) else ''
            })
    
    st.info(f"📋 符合條件的學員：**{len(eligible_students)}** 人")
    
    if eligible_students:
        # 顯示學員列表
        student_df = pd.DataFrame(eligible_students)
        
        st.dataframe(
            student_df[['status_icon', 'name', 'email', 'expire_date', 'status_text', 'company']].rename(columns={
                'status_icon': '狀態',
                'name': '姓名',
                'email': 'Email',
                'expire_date': '到期日',
                'status_text': '到期狀態',
                'company': '公司'
            }),
            use_container_width=True,
            height=200
        )
        
        # 郵件內容設定
        st.markdown("### ✉️ 郵件內容")
        
        course_name = st.session_state.current_file_name.replace('.xlsx', '').replace('.xls', '')
        
        subject = st.text_input(
            "郵件主旨",
            value=f"【證照到期通知】{course_name}"
        )
        
        default_content = f"""{{姓名}} 您好：

您的 {course_name} 證照即將於 {{到期日}} 到期。

為維護您的工作權益，請儘速安排回訓課程。

📋 回覆方式：
• 已報名：請回覆「報名」
• 不報名：請回覆「不報名」
• 暫時無法參加：請回覆「下期再通知」

如有任何問題，歡迎來電洽詢。

謝謝您的配合！"""
        
        content = st.text_area(
            "郵件內容",
            value=default_content,
            height=250,
            help="可使用變數：{姓名}、{到期日}、{公司名稱}"
        )
        
        # 附件
        attachments = st.file_uploader(
            "附件（選填）",
            accept_multiple_files=True,
            key="expiry_attachments"
        )
        
        # 發送按鈕
        col1, col2 = st.columns([3, 1])
        with col1:
            if st.button("📧 開始發送", type="primary", use_container_width=True):
                send_expiry_emails(eligible_students, subject, content, config, attachments)
        with col2:
            if st.button("🔄 重新整理"):
                st.rerun()


def show_broadcast_notification(df, config):
    """顯示統一公告發送介面"""
    st.markdown("### 📣 統一公告")
    
    # 篩選條件
    col1, col2 = st.columns(2)
    
    with col1:
        include_registered = st.checkbox("包含已報名學員", value=True)
    
    with col2:
        include_not_registered = st.checkbox("包含不報名學員", value=False)
    
    # 篩選學員
    eligible_students = []
    
    for idx, row in df.iterrows():
        name = str(row.get('姓名', '')).strip()
        email = str(row.get('Email', '')).strip()
        status = str(row.get('報名狀態', '')).strip()
        
        if not name or not email or '@' not in email:
            continue
        
        # 根據設定篩選
        if status == '已報名' and not include_registered:
            continue
        if status == '不報名' and not include_not_registered:
            continue
        
        eligible_students.append({
            'idx': idx,
            'name': name,
            'email': email,
            'status': status if status else '未回覆',
            'company': str(row.get('公司名稱', '')) if pd.notna(row.get('公司名稱')) else ''
        })
    
    st.info(f"📋 將發送給：**{len(eligible_students)}** 人")
    
    if eligible_students:
        # 顯示學員列表
        with st.expander("📋 檢視發送名單"):
            st.dataframe(
                pd.DataFrame(eligible_students)[['name', 'email', 'status', 'company']].rename(columns={
                    'name': '姓名',
                    'email': 'Email',
                    'status': '狀態',
                    'company': '公司'
                }),
                use_container_width=True
            )
        
        # 郵件內容設定
        st.markdown("### ✉️ 郵件內容")
        
        # 範本選擇
        template_options = {
            '課程開課通知': {
                'subject': '【開課通知】課程即將開課',
                'content': '{姓名} 您好：\n\n感謝您報名本中心課程。\n\n在此通知您課程即將開課，請準時出席。\n\n如有任何問題，歡迎來電洽詢。\n\n祝 學習愉快！'
            },
            '課程異動通知': {
                'subject': '【重要通知】課程異動通知',
                'content': '{姓名} 您好：\n\n本中心課程有異動，請留意以下訊息：\n\n（請在此填寫異動內容）\n\n造成不便敬請見諒，如有任何問題歡迎來電洽詢。'
            },
            '自訂內容': {
                'subject': '【通知】',
                'content': '{姓名} 您好：\n\n'
            }
        }
        
        template = st.selectbox("選擇範本", list(template_options.keys()))
        
        subject = st.text_input(
            "郵件主旨",
            value=template_options[template]['subject']
        )
        
        content = st.text_area(
            "郵件內容",
            value=template_options[template]['content'],
            height=200,
            help="可使用變數：{姓名}、{公司名稱}"
        )
        
        # 附件
        attachments = st.file_uploader(
            "附件（選填）",
            accept_multiple_files=True,
            key="broadcast_attachments"
        )
        
        # 發送按鈕
        if st.button("📧 開始發送公告", type="primary", use_container_width=True):
            send_broadcast_emails(eligible_students, subject, content, config, attachments)


def send_expiry_emails(students, subject, content_template, config, attachments):
    """發送到期通知郵件"""
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    success_count = 0
    fail_count = 0
    results = []
    
    # 處理附件
    attachment_data = []
    if attachments:
        for f in attachments:
            attachment_data.append((f.read(), f.name))
    
    for i, student in enumerate(students):
        status_text.text(f"發送中... {i+1}/{len(students)} - {student['name']}")
        
        # 替換變數
        content = content_template.replace('{姓名}', student['name'])
        content = content.replace('{到期日}', str(student['expire_date']))
        content = content.replace('{公司名稱}', student['company'])
        
        # 發送郵件
        success, message = send_email(
            to_email=student['email'],
            subject=subject,
            content=content,
            config=config,
            attachments=attachment_data if attachment_data else None
        )
        
        if success:
            success_count += 1
            results.append(f"✅ {student['name']} ({student['email']})")
            
            # 記錄已發送
            file_name = st.session_state.current_file_name
            if file_name not in st.session_state.sent_records:
                st.session_state.sent_records[file_name] = {}
            
            record_key = f"{student['name']}_{student['email']}"
            st.session_state.sent_records[file_name][record_key] = {
                'sent_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'type': 'expiry_notification',
                'stage': student.get('stage', '')
            }
        else:
            fail_count += 1
            results.append(f"❌ {student['name']} - {message}")
        
        progress_bar.progress((i + 1) / len(students))
    
    status_text.empty()
    
    # 顯示結果
    if fail_count == 0:
        st.success(f"🎉 發送完成！成功 {success_count} 封")
    else:
        st.warning(f"📧 發送完成！成功 {success_count} 封，失敗 {fail_count} 封")
    
    with st.expander("📋 詳細結果"):
        for result in results:
            st.text(result)


def send_broadcast_emails(students, subject, content_template, config, attachments):
    """發送統一公告郵件"""
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    success_count = 0
    fail_count = 0
    results = []
    
    # 處理附件
    attachment_data = []
    if attachments:
        for f in attachments:
            attachment_data.append((f.read(), f.name))
    
    for i, student in enumerate(students):
        status_text.text(f"發送中... {i+1}/{len(students)} - {student['name']}")
        
        # 替換變數
        content = content_template.replace('{姓名}', student['name'])
        content = content.replace('{公司名稱}', student['company'])
        
        # 發送郵件
        success, message = send_email(
            to_email=student['email'],
            subject=subject,
            content=content,
            config=config,
            attachments=attachment_data if attachment_data else None
        )
        
        if success:
            success_count += 1
            results.append(f"✅ {student['name']} ({student['email']})")
        else:
            fail_count += 1
            results.append(f"❌ {student['name']} - {message}")
        
        progress_bar.progress((i + 1) / len(students))
    
    status_text.empty()
    
    # 顯示結果
    if fail_count == 0:
        st.success(f"🎉 發送完成！成功 {success_count} 封")
    else:
        st.warning(f"📧 發送完成！成功 {success_count} 封，失敗 {fail_count} 封")
    
    with st.expander("📋 詳細結果"):
        for result in results:
            st.text(result)


def show_records_page():
    """顯示發送記錄頁面"""
    st.markdown('<div class="sub-header">📊 發送記錄</div>', unsafe_allow_html=True)
    
    if not st.session_state.sent_records:
        st.info("📭 目前沒有發送記錄")
        return
    
    # 統計
    total_records = sum(len(v) for v in st.session_state.sent_records.values())
    st.metric("📧 總發送記錄", total_records)
    
    st.markdown("---")
    
    # 顯示記錄
    for file_name, records in st.session_state.sent_records.items():
        with st.expander(f"📁 {file_name}（{len(records)} 筆）", expanded=True):
            record_list = []
            for key, info in records.items():
                parts = key.rsplit('_', 1)
                name = parts[0] if len(parts) > 1 else key
                email = parts[1] if len(parts) > 1 else ''
                record_list.append({
                    '姓名': name,
                    'Email': email,
                    '發送時間': info.get('sent_time', ''),
                    '類型': info.get('type', ''),
                    '階段': info.get('stage', '')
                })
            
            if record_list:
                st.dataframe(pd.DataFrame(record_list), use_container_width=True)
            
            # 刪除此課程記錄
            if st.button(f"🗑️ 清除此課程記錄", key=f"del_{file_name}"):
                del st.session_state.sent_records[file_name]
                st.success("已清除")
                st.rerun()
    
    # 清除所有記錄
    st.markdown("---")
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🗑️ 清除所有記錄", type="secondary"):
            st.session_state.sent_records = {}
            st.success("✅ 已清除所有記錄")
            st.rerun()


def show_settings_page():
    """顯示設定頁面"""
    st.markdown('<div class="sub-header">⚙️ 設定</div>', unsafe_allow_html=True)
    
    config = st.session_state.config
    
    # 顯示 Secrets 設定狀態
    st.markdown("### 📋 目前設定")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**公司資訊**")
        st.text(f"公司名稱：{config['company_name']}")
        st.text(f"承辦人：{config['sender_name'] or '（未設定）'}")
        st.text(f"電話：{config['sender_phone'] or '（未設定）'}")
    
    with col2:
        st.markdown("**Gmail 設定**")
        if config['gmail_account']:
            st.text(f"帳號：{config['gmail_account']}")
            st.text(f"密碼：{'*' * 8}（已設定）" if config['gmail_password'] else "密碼：（未設定）")
        else:
            st.warning("尚未設定 Gmail")
    
    st.markdown("---")
    
    # 手動設定（如果 Secrets 沒設定的話）
    st.markdown("### ✏️ 手動設定")
    st.info("💡 如果已在 Streamlit Secrets 設定，以下設定會覆蓋 Secrets 的值（僅限本次使用）")
    
    with st.form("manual_settings"):
        st.markdown("**Gmail 設定**")
        gmail_account = st.text_input(
            "Gmail 帳號",
            value=config['gmail_account'],
            placeholder="your@gmail.com"
        )
        gmail_password = st.text_input(
            "應用程式密碼",
            type="password",
            value=config['gmail_password'],
            placeholder="輸入 16 位應用程式密碼"
        )
        
        st.markdown("**公司資訊**")
        company_name = st.text_input(
            "公司/機構名稱",
            value=config['company_name']
        )
        sender_name = st.text_input(
            "承辦人姓名",
            value=config['sender_name']
        )
        sender_phone = st.text_input(
            "聯絡電話",
            value=config['sender_phone']
        )
        
        st.markdown("**通知設定**")
        notification_days_str = st.text_input(
            "通知天數（用逗號分隔，負數表示過期後）",
            value=", ".join(map(str, config['notification_days']))
        )
        
        submitted = st.form_submit_button("💾 儲存設定", use_container_width=True)
        
        if submitted:
            # 解析通知天數
            try:
                notification_days = [int(x.strip()) for x in notification_days_str.split(',')]
            except:
                notification_days = config['notification_days']
            
            st.session_state.config = {
                'gmail_account': gmail_account,
                'gmail_password': gmail_password,
                'company_name': company_name,
                'sender_name': sender_name,
                'sender_phone': sender_phone,
                'notification_days': notification_days
            }
            st.session_state.gmail_verified = False
            st.success("✅ 設定已儲存！")
            st.rerun()
    
    st.markdown("---")
    
    # 測試連線
    st.markdown("### 🔌 測試 Gmail 連線")
    
    if st.button("測試連線", use_container_width=True):
        with st.spinner("測試中..."):
            success, message = test_gmail_connection(
                st.session_state.config['gmail_account'],
                st.session_state.config['gmail_password']
            )
        
        if success:
            st.session_state.gmail_verified = True
            st.success(f"✅ {message}")
        else:
            st.session_state.gmail_verified = False
            st.error(f"❌ {message}")
    
    # 應用程式密碼說明
    st.markdown("---")
    st.markdown("### ❓ 如何取得 Gmail 應用程式密碼？")
    st.markdown("""
    1. 前往 [Google 帳戶安全性](https://myaccount.google.com/security)
    2. 確認已啟用「**兩步驟驗證**」
    3. 搜尋「**應用程式密碼**」或[點此前往](https://myaccount.google.com/apppasswords)
    4. 選擇「郵件」和「Windows 電腦」
    5. 點擊「產生」
    6. **複製 16 位密碼**（不含空格）
    """)


# ==================== 主程式 ====================

def main():
    """主程式"""
    show_sidebar()
    
    # 根據頁面顯示不同內容
    page = st.session_state.page
    
    if page == 'home':
        show_home_page()
    elif page == 'course':
        show_course_page()
    elif page == 'students':
        show_students_page()
    elif page == 'send':
        show_send_page()
    elif page == 'records':
        show_records_page()
    elif page == 'settings':
        show_settings_page()
    else:
        show_home_page()


if __name__ == "__main__":
    main()
