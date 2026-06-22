# PyKRX Swing Lab

한국 주식을 스윙 투자 관점에서 객관적으로 분석하는 로컬 웹사이트입니다.

- OpenAI API를 사용하지 않습니다.
- DART API를 사용하지 않습니다.
- 투자 추천, 매수/매도 판단을 제공하지 않습니다.
- `pykrx`와 네이버 금융 HTML 데이터를 조합해 추세, 거래량, 거래대금, 시가총액, 외국인/기관 수급을 보여줍니다.

## 실행 준비

### Python 설치

Windows에서는 Python 3.10 이상을 권장합니다.

1. https://www.python.org/downloads/ 에서 Python을 설치합니다.
2. 설치 화면에서 `Add python.exe to PATH`를 체크하면 터미널에서 `python` 명령을 바로 사용할 수 있습니다.

Codex 작업공간에서는 아래 번들 Python을 사용할 수 있습니다.

```powershell
& 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' --version
```

### pykrx 설치

```powershell
& 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pip install pykrx pandas pillow
```

## 현재 프로젝트 실행

현재 프로젝트는 별도 빌드 없이 Python 서버가 정적 화면과 API를 함께 제공합니다.

```powershell
& 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' app.py
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8000
```

## main/dev 폴더 복사 운영법

이 프로젝트는 Git 브랜치 대신 전체 프로젝트 폴더를 복사해서 안정 버전과 개발 버전을 나누어 관리할 수 있습니다. 프론트엔드와 백엔드를 따로 분리하지 않고, 현재처럼 하나의 앱 폴더를 그대로 실행합니다.

권장 폴더 구조:

```text
C:\Users\user\Documents\
├─ 투자-main  안정적으로 실제 사용하는 버전
└─ 투자-dev   새 기능 개발과 실험용 버전
```

운영 원칙:

- 평소 실제 사용은 `투자-main`에서 합니다.
- 새 기능 개발과 수정은 반드시 `투자-dev`에서만 합니다.
- `투자-dev`가 충분히 안정화되면 `투자-main`을 먼저 백업합니다.
- 백업 후 `투자-dev` 폴더를 복사해서 새 `투자-main`으로 교체합니다.
- 기능, UI, 데이터 수집 방식은 폴더 복사만으로 동일하게 유지됩니다.

예시 교체 절차:

```text
1. 투자-main 서버를 종료합니다.
2. 투자-main 폴더를 투자-main-backup-YYYYMMDD 형태로 복사해 백업합니다.
3. 투자-dev 폴더를 복사합니다.
4. 복사한 폴더 이름을 투자-main으로 바꿉니다.
5. 투자-main을 8000번 포트로 다시 실행합니다.
```

## main/dev 동시 실행

두 폴더를 동시에 실행하려면 포트와 캡처 이미지 폴더를 다르게 지정하면 됩니다.

권장 설정:

```text
투자-main: PORT=8000, APP_ENV=main, NAVER_CAPTURE_DIR=static/naver_captures
투자-dev : PORT=8001, APP_ENV=dev,  NAVER_CAPTURE_DIR=static/naver_captures_dev
```

간편 실행 파일:

```text
투자-main\start_main.bat  또는  투자-main\start_main.ps1
투자-dev\start_dev.bat    또는  투자-dev\start_dev.ps1
```

직접 실행할 수도 있습니다.

```powershell
# 투자-main
$env:PORT="8000"
$env:APP_ENV="main"
$env:NAVER_CAPTURE_DIR="static/naver_captures"
& 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' app.py

# 투자-dev
$env:PORT="8001"
$env:APP_ENV="dev"
$env:NAVER_CAPTURE_DIR="static/naver_captures_dev"
& 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' app.py
```

접속 주소:

```text
투자-main: http://127.0.0.1:8000
투자-dev : http://127.0.0.1:8001
```

`NAVER_CAPTURE_DIR`은 네이버 실제 화면 캡처와 외국인/기관 수급 캡처 이미지가 저장되는 임시 폴더입니다. main과 dev를 동시에 켤 때 이 값을 다르게 두면 이미지 파일이 서로 섞이지 않습니다.

`APP_ENV=dev`로 실행하면 사이트 제목이 `Junsu SwingLab_Dev`로 표시되고, `Dev` 글자는 붉은색으로 표시됩니다.

## 프론트엔드/백엔드 분리 여부

현재 운영 방식에서는 프론트엔드와 백엔드를 따로 분리하지 않습니다. `app.py`가 화면 파일과 API를 함께 제공하므로, `투자-main`과 `투자-dev` 모두 전체 프로젝트 폴더를 그대로 복사해서 실행하면 됩니다.

## 프로젝트 구조

- `app.py`: 로컬 웹 서버와 `/api/analyze` API
- `stock_analyzer.py`: pykrx 데이터 분석, 이동평균선, 거래량, 52주 위치, 종합 분석 생성
- `service/naver_scraper.py`: 네이버 금융 크롤링 전담 서비스
- `static/index.html`: 웹사이트 진입 화면
- `static/app.js`: 카드형 분석 화면과 GPT 분석용 복사 기능
- `static/styles.css`: 화면 디자인
- `static/naver_captures/`: 기본 캡처 이미지 저장 위치
- `static/naver_captures_dev/`: dev 실행 시 사용할 수 있는 캡처 이미지 저장 위치
- `start_main.bat`, `start_main.ps1`: 8000번 포트와 기본 캡처 폴더로 실행
- `start_dev.bat`, `start_dev.ps1`: 8001번 포트와 dev 캡처 폴더로 실행

## 네이버 금융 크롤링 구조

네이버 금융 HTML 구조는 변경될 수 있으므로 크롤러는 `service/naver_scraper.py`로 분리했습니다.

수집 대상:

- 시가총액
- 거래대금
- 거래대금 순위
- 외국인 보유율
- 외국인 순매수
- 기관 순매수
- 개인 순매수
- 투자자별 매매동향 표 이미지

네이버 금융 크롤링이 실패해도 사이트 전체가 중단되지 않도록 처리했습니다. 이 경우 화면에는 `네이버 금융 데이터를 가져올 수 없습니다.` 또는 `수급 데이터를 가져올 수 없습니다.`가 표시됩니다.

## 제공 분석

- 기본 시세: 종목명, 종목코드, 현재가, 등락률, 시가, 고가, 저가, 종가, 거래량, 시가총액
- 이동평균선: MA5, MA20, MA60, MA120, 현재가 대비 위치, 정배열, 역배열
- 거래량: 20일 평균 거래량, 오늘 거래량, 거래량 증가율, 구간 해석
- 거래대금: 네이버 금융 거래대금, 추정 거래대금, 시장 내 순위
- 52주 위치: 52주 최고가, 최저가, 최고가 대비 하락률
- 전고점: 최근 60거래일 최고가와 돌파 여부
- 수급: 외국인/기관/개인 5일, 20일 누적 순매수
- 종합 분석: 추세, 거래량, 수급, 시장관심도, 위험요인, 관찰포인트
- GPT 분석용 복사: ChatGPT에 붙여넣을 수 있는 프롬프트 자동 생성

## 자주 발생하는 오류

### 연결이 거부됨

서버가 꺼져 있거나 8000번 포트가 다른 프로그램에서 사용 중일 수 있습니다. 서버를 다시 실행하세요.

```powershell
& 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' app.py
```

### pykrx 데이터를 가져오지 못함

KRX 응답 지연, 휴장일, pykrx 버전 문제로 데이터가 비어 있을 수 있습니다. 잠시 후 다시 시도하거나 `pykrx`를 업데이트하세요.

```powershell
& 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pip install -U pykrx
```

### 네이버 금융 데이터를 가져오지 못함

네이버 금융 HTML 구조가 바뀌었거나 일시적으로 요청이 실패한 경우입니다. 이때는 `service/naver_scraper.py`의 선택자와 표 파싱 로직을 수정하면 됩니다.

### 종목명이 검색되지 않음

6자리 종목코드로 입력하면 가장 안정적입니다.

```text
005930
```

### 외국인/기관 수급 이미지가 보이지 않음

`static/naver_captures/` 폴더에 이미지가 생성되는지 확인하세요. 이미지 생성에는 `pillow` 패키지가 필요합니다.

## 종목 검색 구조

- 종목 검색은 `service/stock_search.py`에서 처리합니다.
- 먼저 pykrx로 KOSPI와 KOSDAQ 전체 종목 DB 생성을 시도합니다.
- pykrx 종목 리스트는 KRX 응답 문제로 0개를 반환하거나 실패할 수 있습니다.
- 이 경우 네이버 금융 검색 fallback을 사용합니다.
- fallback은 하드코딩 종목 목록이 아니라 네이버 금융 종목 페이지와 검색 결과를 기반으로 종목명, 종목코드, 시장 구분을 확인합니다.
- fallback으로 찾은 종목은 `data/stock_universe.json`에 캐시됩니다.
- pykrx가 0개를 반환하면 빈 캐시로 덮어쓰지 않고 기존 캐시를 유지합니다.
- 종목 검색 소스와 주가 OHLCV 수집 소스는 다를 수 있습니다. 종목 확인은 네이버 금융 fallback, 일봉/이동평균 계산은 pykrx 데이터로 진행될 수 있습니다.

## TOP10 데이터 구조

- 외국인/기관 순매수·순매도 TOP10은 `service/naver_top10_service.py`에서 네이버 금융 크롤링 결과로 생성합니다.
- TOP10에는 ETF, ETN, 스팩, 리츠, 우선주, 주요 ETF 운용사명(KODEX, TIGER, ACE, SOL, KBSTAR 등)이 포함된 항목을 제외합니다.
- 한국시간 09:00~16:00 사이에는 마지막 갱신 후 1시간 이상 지났을 때 자동으로 새로고침합니다.
- 장외 시간에는 `data/top10_cache.json`에 저장된 마지막 캐시 데이터를 표시하고, 화면에 “장외 시간: 마지막 갱신 데이터” 안내를 표시합니다.
- “TOP10 새로고침” 버튼은 네이버 금융 크롤링을 즉시 시도합니다. 실패하면 기존 캐시는 유지하고 오류 메시지만 표시합니다.
- 네이버 금융 HTML 구조가 바뀌면 TOP10 크롤링이 실패할 수 있으며, 이 경우 `service/naver_top10_service.py`의 파싱 로직을 수정해야 합니다.
- 캡처 이미지는 임시 저장되며 오래된 파일은 자동 삭제됩니다.
