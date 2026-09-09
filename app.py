"""
AI 소음 측정 시간 변환기 (Streamlit 버전)

소음 측정기 세션 보고서 PDF를 업로드하면
- 근로자명 / 시작시간 / 종료시간 / 소음값(dB) / 코드값(HHMM+HHMM)
을 자동으로 추출해 표와 엑셀로 정리해 주는 도구입니다.

소음값(dB) 추출 규칙
1) 로그된 데이터 차트 아래 "제외된 범위" 상자가 있으면 그 옆의 Lavg-1 dB 값을 사용
2) 텍스트로 못 찾으면 차트 이미지를 OCR로 다시 읽어서 찾음
3) 그래도 없으면 요약 데이터 패널의 Lavg 값을 대신 사용
"""

import io
import re
import bisect
from datetime import datetime

import streamlit as st
import pandas as pd
import pdfplumber

# OCR 관련 라이브러리는 배포 환경에 없을 수도 있으므로 안전하게 임포트
try:
    from pdf2image import convert_from_bytes
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

MAX_FILES = 100

st.set_page_config(page_title="AI 소음 측정 시간 변환기", page_icon="🎧", layout="wide")


# ----------------------------------------------------------------------
# 파싱 유틸리티
# ----------------------------------------------------------------------

def pad2(n: int) -> str:
    return str(n).zfill(2)


def to24(hour: int, ampm: str) -> int:
    hour = int(hour)
    if ampm == "오전":
        if hour == 12:
            hour = 0
    elif ampm == "오후":
        if hour != 12:
            hour += 12
    return hour


def extract_seq_from_filename(filename: str):
    m = re.match(r"^(\d+)", filename or "")
    return int(m.group(1)) if m else None


def grab_time(clean_text: str, label_pattern: str):
    m = re.search(label_pattern, clean_text)
    if not m:
        return None
    window = clean_text[m.end(): m.end() + 60]
    tm = re.search(r"(오전|오후)\s*(\d{1,2})\s*:\s*(\d{2})", window)
    if not tm:
        return None
    h24 = to24(tm.group(2), tm.group(1))
    return pad2(h24) + pad2(tm.group(3))


def extract_name(clean_text: str) -> str:
    m = re.search(r"이름\s*[:\-]?\s*(.+?)\s*(?:시작\s*시간|중지\s*시간)", clean_text)
    name = m.group(1).strip() if m else ""
    if "-" in name:
        name = name.split("-")[-1].strip()
    return name


def extract_summary_lavg(clean_text: str):
    m = re.search(r"Lavg\s+1\s+([\d.]+)\s*dB", clean_text)
    return m.group(1) if m else None


LAVG_PATTERN = re.compile(r"Lavg-?1?\s*[:\-]?\s*([\d.]+)\s*dB")


def extract_excluded_lavg_from_words(pages_words):
    """
    pdfplumber의 단어 좌표(x0, top)를 이용해 "선택된 범위 / 제외된 범위" 박스에서
    오른쪽(제외된 범위) 열의 Lavg-1 값을 찾는다.
    같은 줄(top 좌표가 비슷한 단어들)을 하나로 묶어 문장을 재구성한 뒤,
    Lavg-1 패턴이 매치된 위치에 가장 가까운 단어의 x0를 그 매치의 x좌표로 사용한다.
    선택된 범위가 항상 왼쪽, 제외된 범위가 항상 오른쪽에 오므로
    x좌표가 가장 큰(오른쪽) 매치를 제외된 범위 값으로 판단한다.
    """
    candidates = []
    for page_no, words in pages_words:
        lines = {}
        for w in words:
            key = round(w["top"] / 2)  # 약간의 오차 허용
            lines.setdefault(key, []).append(w)

        for line_words in lines.values():
            line_words.sort(key=lambda w: w["x0"])
            buf = ""
            marks = []  # (문자열 offset, x0)
            for w in line_words:
                marks.append((len(buf), w["x0"]))
                buf += w["text"] + " "

            for m in LAVG_PATTERN.finditer(buf):
                idx = m.start()
                x = marks[0][1] if marks else 0
                for pos, x0 in marks:
                    if pos <= idx:
                        x = x0
                    else:
                        break
                candidates.append((x, m.group(1)))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[-1][1]


def extract_excluded_lavg_by_ocr(pdf_bytes: bytes):
    if not OCR_AVAILABLE:
        return None
    try:
        images = convert_from_bytes(pdf_bytes, dpi=200, first_page=1, last_page=1)
        if not images:
            return None
        text = pytesseract.image_to_string(images[0], lang="kor+eng")
        clean = re.sub(r"\s+", " ", text).strip()
        idx = re.search(r"제외된?\s*범위", clean)
        search_text = clean[idx.start():] if idx else clean
        matches = list(re.finditer(r"Lavg-?1?[:\-]?\s*([\d.]+)\s*d[BE8]", search_text, re.IGNORECASE))
        if matches:
            return matches[-1].group(1)
        return None
    except Exception:
        return None


def parse_pdf(file_name: str, file_bytes: bytes):
    result = {
        "file": file_name,
        "seq": extract_seq_from_filename(file_name),
        "name": "",
        "start": "",
        "end": "",
        "excluded_lavg": "",
        "ok": False,
    }

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            full_text = ""
            pages_words = []
            for i, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                full_text += page_text + " "
                words = page.extract_words()
                pages_words.append((i, words))

            clean = re.sub(r"\s+", " ", full_text).strip()

            result["name"] = extract_name(clean)
            result["start"] = grab_time(clean, r"시작\s*시간") or ""
            result["end"] = grab_time(clean, r"중지\s*시간") or ""

            excluded = extract_excluded_lavg_from_words(pages_words)
            summary = extract_summary_lavg(clean)

            if not excluded:
                excluded = extract_excluded_lavg_by_ocr(file_bytes)
            if not excluded and summary:
                excluded = summary

            result["excluded_lavg"] = excluded or ""
    except Exception as e:
        result["error"] = str(e)

    result["ok"] = bool(result["name"] and result["start"] and result["end"] and result["excluded_lavg"])
    return result


def code_for(row) -> str:
    if row["start"] and row["end"]:
        return f"{row['start']}{row['end']}"
    return ""


# ----------------------------------------------------------------------
# Streamlit UI
# ----------------------------------------------------------------------

st.markdown("##### SESSION REPORT → EXCEL")
st.title("AI 소음 측정 시간 변환기")
st.write(
    "소음 측정기 세션 보고서 PDF를 올리면 **이름**, **시작 시간**, **중지 시간**을 자동으로 읽어 "
    "**HHMM+HHMM** 형식(예: 09001600)으로 정리해 드려요. 여러 파일을 한 번에 올릴 수 있고(최대 100개), "
    "표에서 값을 바로 고칠 수 있어요."
)

if not OCR_AVAILABLE:
    st.warning(
        "OCR 라이브러리(pdf2image/pytesseract)가 설치되어 있지 않아요. "
        "requirements.txt / packages.txt를 확인해 주세요. "
        "OCR이 없으면 '제외된 범위'가 이미지로만 되어 있는 PDF는 요약 Lavg 값으로 대체돼요."
    )

if "rows" not in st.session_state:
    st.session_state.rows = {}  # filename -> row dict

uploaded_files = st.file_uploader(
    "PDF 파일을 올려주세요 (여러 개 선택 가능, 최대 100개)",
    type=["pdf"],
    accept_multiple_files=True,
)

col_a, col_b = st.columns([1, 1])
with col_a:
    if st.button("전체 지우기"):
        st.session_state.rows = {}
        st.rerun()

if uploaded_files:
    files_to_process = uploaded_files[:MAX_FILES]
    if len(uploaded_files) > MAX_FILES:
        st.warning(f"한 번에 최대 {MAX_FILES}개까지 처리할 수 있어요. 앞쪽 {MAX_FILES}개만 처리했어요.")

    new_files = [f for f in files_to_process if f.name not in st.session_state.rows]

    if new_files:
        progress = st.progress(0, text="처리를 시작합니다...")
        for i, f in enumerate(new_files):
            progress.progress((i) / len(new_files), text=f"({i+1}/{len(new_files)}) {f.name} 처리 중...")
            file_bytes = f.read()
            parsed = parse_pdf(f.name, file_bytes)
            st.session_state.rows[f.name] = parsed
        progress.progress(1.0, text="완료!")
        progress.empty()

if st.session_state.rows:
    rows = list(st.session_state.rows.values())
    rows.sort(key=lambda r: (r["seq"] if r["seq"] is not None else float("inf"), r["file"]))

    df = pd.DataFrame([
        {
            "순번": r["seq"] if r["seq"] is not None else "",
            "파일명": r["file"],
            "근로자명": r["name"],
            "시작시간": r["start"],
            "종료시간": r["end"],
            "소음값(dB)": r["excluded_lavg"],
            "코드값": code_for(r),
            "상태": "완료" if r["ok"] else "확인필요",
        }
        for r in rows
    ])

    st.subheader(f"추출 결과 ({len(df)} / {MAX_FILES}건)")
    st.caption("값이 잘못 인식됐다면 표에서 직접 클릭해서 수정한 뒤 엑셀로 받으세요. (코드값은 자동 재계산되지 않으니 시작/종료시간을 고치면 코드값도 함께 수정해 주세요)")

    edited_df = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "순번": st.column_config.NumberColumn(width="small"),
            "상태": st.column_config.TextColumn(width="small", disabled=True),
        },
        key="editor",
    )

    # 엑셀 다운로드
    export_df = edited_df.drop(columns=["상태"], errors="ignore")

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="소음측정시간")
        ws = writer.sheets["소음측정시간"]
        widths = {"A": 7, "B": 26, "C": 16, "D": 12, "E": 12, "F": 13, "G": 14}
        for col, w in widths.items():
            ws.column_dimensions[col].width = w
    buffer.seek(0)

    fname = f"소음측정시간_{datetime.now().strftime('%Y%m%d')}.xlsx"
    st.download_button(
        "엑셀 다운로드",
        data=buffer,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
else:
    st.info("아직 업로드된 보고서가 없어요.")

st.divider()
st.caption(
    "코드값은 시작 시간과 종료 시간을 HHMM 형식으로 이어붙인 값이에요 (예: 09:00 → 16:00 은 09001600). "
    "소음값(dB)은 차트의 '제외된 범위' 값을 우선 사용하고, 해당 구간이 없으면 요약 데이터 패널의 Lavg 값을 대신 넣어요."
)
