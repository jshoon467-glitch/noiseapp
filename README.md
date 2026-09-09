# AI 소음 측정 시간 변환기 (Streamlit)

소음 측정기 세션 보고서 PDF를 업로드하면 근로자명·시작시간·종료시간·소음값(dB)·코드값을
자동으로 추출해 표와 엑셀로 정리해 주는 Streamlit 앱입니다.

## 소음값(dB) 추출 규칙
1. 로그된 데이터 차트 아래 "제외된 범위" 상자가 있으면 그 옆의 `Lavg-1` dB 값을 사용
2. 텍스트로 못 찾으면(차트가 이미지인 경우) OCR로 이미지를 다시 읽어서 찾음
3. 그래도 없으면 요약 데이터 패널의 `Lavg` 값을 대신 사용

## 파일 구성
- `app.py` — 메인 Streamlit 앱
- `requirements.txt` — Python 패키지 목록
- `packages.txt` — Streamlit Community Cloud가 설치할 시스템(apt) 패키지 목록 (OCR/PDF 렌더링용)

## GitHub에 올리기
```bash
cd streamlit_app
git init
git add .
git commit -m "AI 소음 측정 시간 변환기"
git branch -M main
git remote add origin https://github.com/<계정명>/<저장소명>.git
git push -u origin main
```

## Streamlit Community Cloud로 배포하기
1. https://share.streamlit.io 접속 후 GitHub 계정으로 로그인
2. "New app" 클릭
3. 방금 올린 저장소 / 브랜치(main) / 파일(`app.py`) 선택
4. Deploy 클릭 — 몇 분 안에 `https://<앱이름>.streamlit.app` 형태의 공개 URL이 생성됩니다.

`packages.txt`가 저장소 루트(=`app.py`와 같은 폴더)에 있어야 Streamlit Cloud가
OCR에 필요한 `poppler-utils`, `tesseract-ocr`, `tesseract-ocr-kor`를 자동으로 설치합니다.

## 로컬에서 먼저 테스트하기 (선택)
```bash
pip install -r requirements.txt
# macOS: brew install poppler tesseract tesseract-lang
# Ubuntu/Debian: sudo apt-get install poppler-utils tesseract-ocr tesseract-ocr-kor
streamlit run app.py
```

## 참고
- 한 번에 최대 100개 PDF까지 처리하도록 제한을 걸어두었습니다 (`app.py`의 `MAX_FILES`에서 조정 가능).
- 표(`데이터 편집기`)에서 자동 인식이 틀린 값을 바로 클릭해서 고칠 수 있습니다.
  시작/종료시간을 고친 경우 코드값은 자동으로 재계산되지 않으니 코드값 칸도 함께 수정해 주세요.
- OCR 관련 패키지가 설치되지 않은 환경에서도 앱은 정상 동작하며, 이 경우 "제외된 범위"가
  이미지로만 되어 있는 PDF는 자동으로 요약 데이터 패널의 Lavg 값으로 대체됩니다.
