"""Rowsetta Streamlit app - steps 1 and 8 (question in, answer screen out).

Owner: TBD
Run: streamlit run app.py
"""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

from rowsetta.pipeline import answer
from rowsetta.settings import Settings

load_dotenv()
settings = Settings.from_env()

st.set_page_config(page_title="Rowsetta", layout="wide")
st.title("Rowsetta")
st.caption("Türkçe soru → doğrulanmış SQL → tablo ve grafik · UCI Online Retail (GBP)")

question = st.text_input("Sorunuz", placeholder="Mayıs 2011'de Fransa ve Almanya'nın net satışını karşılaştır")

if question:
    try:
        result = answer(question, settings)
    except NotImplementedError as exc:
        st.warning(f"Henüz yazılmadı: {exc}")
        st.stop()

    st.subheader("Durum")
    st.write(result.status)
    if result.message:
        st.info(result.message)
    if result.sql:
        st.subheader("Çalıştırılan SQL")
        st.code(result.sql, language="sql")
        st.json(result.params)
    if result.columns:
        st.subheader("Sonuç")
        st.dataframe([dict(zip(result.columns, row)) for row in result.rows])
        if result.truncated:
            st.caption(f"İlk {settings.max_rows} satır gösteriliyor.")
    # TODO(owner): chart rendering from result.chart (bar / line / value card)
    if result.timings_ms:
        st.caption(" · ".join(f"{k}: {v:.0f} ms" for k, v in result.timings_ms.items()))
