import os
import streamlit as st
import pandas as pd
import numpy as np

# Generate fake data
np.random.seed(42)
n_rows = 5000
data = pd.DataFrame({
    "fare_amount": np.random.uniform(5, 60, n_rows),
    "trip_distance": np.random.uniform(0.5, 20, n_rows),
    "pickup_zip": np.random.choice([10003, 10001, 10002, 11238, 11201], n_rows),
    "dropoff_zip": np.random.choice([10003, 10001, 10002, 11238, 11201], n_rows),
})

st.set_page_config(layout="wide")

st.header("Taxi fare distribution !!! :)")
col1, col2 = st.columns([3, 1])
with col1:
    st.scatter_chart(
        data=data, height=400, width=700, y="fare_amount", x="trip_distance"
    )
with col2:
    st.subheader("Predict fare")
    pickup = st.text_input("From (zipcode)", value="10003")
    dropoff = st.text_input("To (zipcode)", value="11238")
    d = data[
        (data["pickup_zip"] == int(pickup)) & (data["dropoff_zip"] == int(dropoff))
    ]
    st.write(f"# **${d['fare_amount'].mean() if len(d) > 0 else 99:.2f}**")

st.dataframe(data=data, height=600, use_container_width=True)
