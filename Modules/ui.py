import streamlit as st

def inject_base_css():
    st.markdown("""
        <style>
        div.stButton > button {
            background-color: white;
            color: #9966ff;
            font-weight: bold;
            border-radius: 5px;
            margin-bottom: 5px;
            border: 1px solid #9966ff;
        }
        div.stButton > button:hover {
            background-color: #9966ff;
            color: white;
        }
        div.stButton > button:focus {
            outline: 2px solid #9966ff !important;
            box-shadow: 0 0 0 2px #9966ff33 !important; /* leve brilho */
        }
        </style>
    """, unsafe_allow_html=True)

