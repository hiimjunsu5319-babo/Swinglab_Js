const root = document.getElementById("root");
// Render 단독 배포: "" 유지
// GitHub Pages + Render API 분리 시: "https://내-render주소.onrender.com" 로 변경
const API_BASE = "";

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

function resourceUrl(url) {
  if (!url || !API_BASE || /^(https?:|data:|blob:)/i.test(url)) return url;
  return url.startsWith("/") ? `${API_BASE}${url}` : url;
}

function loadLocalJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function saveLocalJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Local storage is optional; the app keeps working without it.
  }
}

const state = {
  query: "",
  quoteMode: "NAVER",
  loading: false,
  result: null,
  error: "",
  copied: false,
  memos: [],
  purchases: [],
  sales: [],
  reportComments: {},
  favorites: [],
  recentSearches: loadLocalJson("junsu_recent_searches", []),
  lastPrices: loadLocalJson("junsu_last_prices", {}),
  rankings: null,
  rankingLoading: false,
  rankingError: "",
  candidatesOpen: false,
  candidates: null,
  candidatesLoading: false,
  candidatesError: "",
  top10Collapsed: false,
  memoListCollapsed: false,
  watchListCollapsed: false,
  memoAddOpen: false,
  purchaseAddOpen: false,
  memoPages: {},
  favoritesCollapsed: false,
  showReport: false,
  reportAddOpen: false,
  reportAdd: { ticker: "", name: "", price: "", quantity: "", note: "" },
  commentOpen: {},
  commentDrafts: {},
  editingPositionTicker: "",
  editingPositionDraft: {},
  reportSaved: false,
  searchCandidates: [],
  activePanel: "",
  memoDraft: "",
  selectedMemoId: "",
  memoSaved: false,
  editingMemoId: "",
  editingMemoDraft: "",
  memoListSaved: false,
  memoAdd: { ticker: "", name: "", note: "" },
  purchaseAdd: { ticker: "", name: "", price: "", quantity: "", note: "" },
  buyPrice: "",
  buyQuantity: "",
  buyNote: "",
  buySaved: false,
  imageCopied: false,
  flowImageCopied: false,
  imagesCopied: false,
  calcPrice: "",
  calcQuantity: "",
  calcReturnRate: "",
  calcTargetPrice: "",
  calcTargetValue: "",
  calcMode: "rate",
  saleInputs: {},
  appConfig: { env: "main", isDev: false, title: "Junsu SwingLab" },
};

async function init() {
  await Promise.all([loadAppConfig(), loadMemos(), loadPurchases(), loadSales(), loadReportComments(), loadFavorites(), loadRankings()]);
  render();
}

async function loadAppConfig() {
  try {
    const response = await fetch(apiUrl("/api/app-config"));
    if (response.ok) {
      state.appConfig = await response.json();
      document.title = state.appConfig.title || "Junsu SwingLab";
    }
  } catch {
    state.appConfig = { env: "main", isDev: false, title: "Junsu SwingLab" };
  }
}

async function loadMemos() {
  try {
    const response = await fetch(apiUrl("/api/memos"));
    state.memos = response.ok ? await response.json() : [];
  } catch {
    state.memos = [];
  }
}

async function loadPurchases() {
  try {
    const response = await fetch(apiUrl("/api/purchases"));
    state.purchases = response.ok ? await response.json() : [];
  } catch {
    state.purchases = [];
  }
}

async function loadSales() {
  try {
    const response = await fetch(apiUrl("/api/sales"));
    state.sales = response.ok ? await response.json() : [];
  } catch {
    state.sales = [];
  }
}

async function loadReportComments() {
  try {
    const response = await fetch(apiUrl("/api/report-comments"));
    state.reportComments = response.ok ? await response.json() : {};
  } catch {
    state.reportComments = {};
  }
}

async function loadFavorites() {
  try {
    const response = await fetch(apiUrl("/api/favorites"));
    state.favorites = response.ok ? await response.json() : [];
  } catch {
    state.favorites = [];
  }
}

async function loadRankings() {
  state.rankingLoading = true;
  state.rankingError = "";
  try {
    const response = await fetch(apiUrl("/api/top10"));
    const payload = await response.json();
    state.rankings = response.ok ? payload : null;
    state.rankingError = response.ok ? payload.error || "" : payload.error || "TOP10 데이터를 가져올 수 없습니다.";
  } catch {
    state.rankings = null;
    state.rankingError = "TOP10 데이터를 가져올 수 없습니다.";
  } finally {
    state.rankingLoading = false;
  }
}

async function refreshRankings() {
  state.rankingLoading = true;
  state.rankingError = "";
  render();
  try {
    const response = await fetch(apiUrl("/api/top10/refresh"), { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "TOP10 새로고침에 실패했습니다.");
    state.rankings = payload;
    state.rankingError = payload.error || "";
  } catch (error) {
    state.rankingError = error.message;
  } finally {
    state.rankingLoading = false;
    state.top10Collapsed = false;
    render();
  }
}

async function loadCandidates(force = false) {
  state.candidatesLoading = true;
  state.candidatesError = "";
  render();
  try {
    const response = await fetch(apiUrl(force ? "/api/candidates/refresh" : "/api/candidates"), {
      method: force ? "POST" : "GET",
    });
    const payload = await readJsonResponse(response, "매수 후보 스캔 응답이 비어 있습니다. dev 서버를 재시작한 뒤 다시 눌러 주세요.");
    if (!response.ok) {
      if (response.status === 404 || payload.error === "Not found") {
        throw new Error("매수 후보 API가 아직 서버에 반영되지 않았습니다. 투자-dev 서버를 재시작한 뒤 다시 눌러 주세요.");
      }
      throw new Error(payload.error || "매수 후보 데이터를 가져올 수 없습니다.");
    }
    state.candidates = payload;
    state.candidatesError = payload.error || "";
  } catch (error) {
    state.candidatesError = error.message;
  } finally {
    state.candidatesLoading = false;
    render();
  }
}

async function readJsonResponse(response, emptyMessage) {
  const text = await response.text();
  if (!text.trim()) {
    throw new Error(emptyMessage);
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("서버 응답을 JSON으로 읽지 못했습니다. dev 서버를 재시작한 뒤 다시 시도해 주세요.");
  }
}

function render() {
  root.innerHTML = `
    <div class="app">
      <header class="topbar">
        <div class="topbar-inner">
          <button id="home-button" class="brand-button" type="button">
            <span>Junsu</span> SwingLab${state.appConfig.isDev ? `_<b class="dev-mark">Dev</b>` : ""}
          </button>
          <div class="topbar-tools">
            ${calculatorView()}
            <button id="search-focus-button" class="nav-action-button" type="button">종목 검색</button>
            <button id="my-report-button" class="report-button ${state.showReport ? "is-active" : ""}" type="button">매매일지</button>
            <span class="badge">No OpenAI API · No DART</span>
            <button class="settings-button" type="button">설정</button>
          </div>
        </div>
      </header>

      <main class="main">
        ${state.showReport ? myReportView() : ""}
        <section class="home-grid ${state.top10Collapsed ? "rankings-collapsed" : ""}">
          <div class="home-main">
            <section class="search-panel">
              <div>
                <h1>종목명 또는 종목코드를 입력하세요</h1>
                <p>투자 추천 없이 추세, 거래량, 거래대금, 시가총액, 외국인/기관 수급을 객관적으로 분석합니다.</p>
              </div>
              <form id="analyze-form" class="analyze-form">
                <input id="query" autocomplete="off" placeholder="예: 삼성전자 또는 005930" value="${escapeHtml(state.query)}" />
                <button type="submit" ${state.loading ? "disabled" : ""}>${state.loading ? "분석 중" : "분석하기"}</button>
              </form>
              <div class="quote-mode">
                <label><input type="radio" name="quote-mode" value="NAVER" ${state.quoteMode === "NAVER" ? "checked" : ""} /> NXT 포함/네이버 기준</label>
                <label><input type="radio" name="quote-mode" value="KRX" ${state.quoteMode === "KRX" ? "checked" : ""} /> KRX 정규장 기준</label>
              </div>
              <div class="source-warning">NXT 포함 시세와 KRX 정규장 시세는 다를 수 있습니다. 장중 현재가/거래량/거래대금은 잠정 데이터로 표시됩니다.</div>
              <div class="quick-list">
                ${recentSearchButtonsView()}
              </div>
              ${state.error ? `<div class="error">${escapeHtml(state.error)}</div>` : ""}
            </section>
            ${state.loading ? loadingView() : ""}
            ${state.result ? resultView(state.result) : ""}
            ${memoListView()}
            ${purchaseListView()}
            ${candidateListView()}
          </div>
          ${rankingPanelView()}
        </section>

        ${!state.loading && !state.result ? emptyView() : ""}
        ${state.candidatesOpen ? candidateModalView() : ""}
      </main>
    </div>
  `;

  bindEvents();
}

function bindEvents() {
  document.getElementById("home-button").addEventListener("click", goHome);
  document.getElementById("analyze-form").addEventListener("submit", analyze);
  document.getElementById("query").addEventListener("input", (event) => {
    state.query = event.target.value;
  });
  document.querySelectorAll("input[name='quote-mode']").forEach((input) => {
    input.addEventListener("change", () => {
      state.quoteMode = input.value;
    });
  });
  document.querySelectorAll(".chip").forEach((button) => {
    button.addEventListener("click", () => analyzeByQuery(button.dataset.code));
  });
  document.querySelectorAll("[data-search-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      state.candidatesOpen = false;
      analyzeByQuery(button.dataset.searchTicker);
    });
  });
  document.querySelectorAll("[data-candidate-favorite]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      toggleFavoriteItem({
        ticker: button.dataset.candidateFavorite,
        name: button.dataset.candidateName || button.dataset.candidateFavorite,
      });
    });
    button.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      event.stopPropagation();
      toggleFavoriteItem({
        ticker: button.dataset.candidateFavorite,
        name: button.dataset.candidateName || button.dataset.candidateFavorite,
      });
    });
  });
  document.querySelectorAll("[data-delete-purchase-id]").forEach((button) => {
    button.addEventListener("click", () => deletePurchase(button.dataset.deletePurchaseId));
  });
  document.querySelectorAll("[data-edit-memo-id]").forEach((button) => {
    button.addEventListener("click", () => openListMemoEditor(button.dataset.editMemoId));
  });
  document.querySelectorAll("[data-memo-nav]").forEach((button) => {
    button.addEventListener("click", () => {
      const ticker = button.dataset.memoTicker;
      const direction = Number(button.dataset.memoNav) || 0;
      const group = groupedMemos().find((item) => item.ticker === ticker);
      if (!group) return;
      const current = state.memoPages[ticker] || 0;
      const next = (current + direction + group.memos.length) % group.memos.length;
      state.memoPages = { ...state.memoPages, [ticker]: next };
      render();
    });
  });
  const listMemoInput = document.getElementById("list-memo-draft");
  if (listMemoInput) {
    listMemoInput.addEventListener("input", (event) => {
      state.editingMemoDraft = event.target.value;
      state.memoListSaved = false;
    });
  }
  const saveListMemoButton = document.getElementById("save-list-memo");
  if (saveListMemoButton) saveListMemoButton.addEventListener("click", saveListMemo);
  const cancelListMemoButton = document.getElementById("cancel-list-memo");
  if (cancelListMemoButton) {
    cancelListMemoButton.addEventListener("click", () => {
      state.editingMemoId = "";
      state.editingMemoDraft = "";
      state.memoListSaved = false;
      render();
    });
  }
  const deleteListMemoButton = document.getElementById("delete-list-memo");
  if (deleteListMemoButton) deleteListMemoButton.addEventListener("click", deleteListMemo);
  document.querySelectorAll("[data-memo-add-field]").forEach((input) => {
    input.addEventListener("input", (event) => {
      state.memoAdd[event.target.dataset.memoAddField] = event.target.value;
    });
  });
  const saveMemoAddButton = document.getElementById("save-memo-add");
  if (saveMemoAddButton) saveMemoAddButton.addEventListener("click", saveMemoAdd);

  const memoButton = document.getElementById("open-memo");
  if (memoButton) memoButton.addEventListener("click", () => openPanel("memo"));
  const buyButton = document.getElementById("open-buy");
  if (buyButton) buyButton.addEventListener("click", () => openPanel("buy"));
  const favoriteButton = document.getElementById("save-favorite");
  if (favoriteButton) favoriteButton.addEventListener("click", saveFavorite);
  const myReportButton = document.getElementById("my-report-button");
  if (myReportButton) {
    myReportButton.addEventListener("click", () => {
      state.showReport = !state.showReport;
      render();
    });
  }
  const searchFocusButton = document.getElementById("search-focus-button");
  if (searchFocusButton) {
    searchFocusButton.addEventListener("click", () => {
      document.getElementById("query")?.focus();
      document.querySelector(".search-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
  const reportPreviewButton = document.getElementById("open-report-preview");
  if (reportPreviewButton) {
    reportPreviewButton.addEventListener("click", () => {
      state.showReport = true;
      render();
    });
  }
  const topCopyButton = document.getElementById("copy-prompt-top");
  if (topCopyButton) topCopyButton.addEventListener("click", copyPrompt);
  const topCopySummaryImageButton = document.getElementById("copy-summary-image-top");
  if (topCopySummaryImageButton) topCopySummaryImageButton.addEventListener("click", copySummaryImage);
  const topCopyFlowImageButton = document.getElementById("copy-flow-image-top");
  if (topCopyFlowImageButton) topCopyFlowImageButton.addEventListener("click", copyFlowImage);

  const memoInput = document.getElementById("memo-draft");
  if (memoInput) {
    memoInput.addEventListener("input", (event) => {
      state.memoDraft = event.target.value;
      state.memoSaved = false;
    });
  }
  const saveMemoButton = document.getElementById("save-memo");
  if (saveMemoButton) saveMemoButton.addEventListener("click", saveMemo);
  document.querySelectorAll("[data-memo-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedMemoId = button.dataset.memoId;
      render();
    });
  });
  const deleteMemoButton = document.getElementById("delete-memo");
  if (deleteMemoButton) deleteMemoButton.addEventListener("click", deleteSelectedMemo);

  const buyPrice = document.getElementById("buy-price");
  if (buyPrice) buyPrice.addEventListener("input", (event) => (state.buyPrice = event.target.value));
  const buyQuantity = document.getElementById("buy-quantity");
  if (buyQuantity) buyQuantity.addEventListener("input", (event) => (state.buyQuantity = event.target.value));
  const buyNote = document.getElementById("buy-note");
  if (buyNote) buyNote.addEventListener("input", (event) => (state.buyNote = event.target.value));
  const saveBuyButton = document.getElementById("save-buy");
  if (saveBuyButton) saveBuyButton.addEventListener("click", savePurchase);
  document.querySelectorAll("[data-sale-field]").forEach((input) => {
    input.addEventListener("input", (event) => {
      const ticker = event.target.dataset.saleTicker;
      const field = event.target.dataset.saleField;
      state.saleInputs[ticker] = { ...(state.saleInputs[ticker] || {}), [field]: event.target.value };
      updateReportSalePreview(ticker);
    });
  });
  document.querySelectorAll("[data-save-sale]").forEach((button) => {
    button.addEventListener("click", () => saveSale(button.dataset.saveSale));
  });
  document.querySelectorAll("[data-delete-report-ticker]").forEach((button) => {
    button.addEventListener("click", () => deleteReportTicker(button.dataset.deleteReportTicker));
  });
  document.querySelectorAll("[data-edit-position]").forEach((button) => {
    button.addEventListener("click", () => openPositionEditor(button.dataset.editPosition));
  });
  document.querySelectorAll("[data-cancel-position-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      state.editingPositionTicker = "";
      state.editingPositionDraft = {};
      render();
    });
  });
  document.querySelectorAll("[data-position-field]").forEach((input) => {
    input.addEventListener("input", (event) => {
      state.editingPositionDraft[event.target.dataset.positionField] = event.target.value;
    });
  });
  document.querySelectorAll("[data-save-position]").forEach((button) => {
    button.addEventListener("click", () => savePositionEdit(button.dataset.savePosition));
  });
  document.querySelectorAll("[data-delete-sale]").forEach((button) => {
    button.addEventListener("click", () => deleteSale(button.dataset.deleteSale));
  });
  document.querySelectorAll("[data-toggle-comment]").forEach((button) => {
    button.addEventListener("click", () => {
      const ticker = button.dataset.toggleComment;
      state.commentOpen[ticker] = !state.commentOpen[ticker];
      if (state.commentOpen[ticker] && state.commentDrafts[ticker] === undefined) {
        state.commentDrafts[ticker] = state.reportComments[ticker]?.comment || "";
      }
      render();
    });
  });
  document.querySelectorAll("[data-comment-field]").forEach((input) => {
    input.addEventListener("input", (event) => {
      state.commentDrafts[event.target.dataset.commentField] = event.target.value;
    });
  });
  document.querySelectorAll("[data-save-comment]").forEach((button) => {
    button.addEventListener("click", () => saveReportComment(button.dataset.saveComment));
  });
  document.querySelectorAll("[data-delete-comment]").forEach((button) => {
    button.addEventListener("click", () => deleteReportComment(button.dataset.deleteComment));
  });
  const toggleReportAddButton = document.getElementById("toggle-report-add");
  if (toggleReportAddButton) {
    toggleReportAddButton.addEventListener("click", () => {
      state.reportAddOpen = !state.reportAddOpen;
      state.reportSaved = false;
      render();
    });
  }
  document.querySelectorAll("[data-report-add-field]").forEach((input) => {
    input.addEventListener("input", (event) => {
      state.reportAdd[event.target.dataset.reportAddField] = event.target.value;
      state.reportSaved = false;
    });
  });
  const saveReportAddButton = document.getElementById("save-report-add");
  if (saveReportAddButton) saveReportAddButton.addEventListener("click", saveReportPurchase);
  document.querySelectorAll("[data-purchase-add-field]").forEach((input) => {
    input.addEventListener("input", (event) => {
      state.purchaseAdd[event.target.dataset.purchaseAddField] = event.target.value;
    });
  });
  const savePurchaseAddButton = document.getElementById("save-purchase-add");
  if (savePurchaseAddButton) savePurchaseAddButton.addEventListener("click", savePurchaseAdd);

  const copyButton = document.getElementById("copy-prompt");
  if (copyButton) copyButton.addEventListener("click", copyPrompt);
  const copyImageButton = document.getElementById("copy-summary-image");
  if (copyImageButton) copyImageButton.addEventListener("click", copySummaryImage);
  const copyFlowImageButton = document.getElementById("copy-flow-image");
  if (copyFlowImageButton) copyFlowImageButton.addEventListener("click", copyFlowImage);
  const refreshTop10Button = document.getElementById("refresh-top10");
  if (refreshTop10Button) refreshTop10Button.addEventListener("click", refreshRankings);
  const openCandidatesButton = document.getElementById("open-candidates");
  if (openCandidatesButton) {
    openCandidatesButton.addEventListener("click", () => {
      state.candidatesOpen = true;
      render();
      if (!state.candidates && !state.candidatesLoading) loadCandidates(false);
    });
  }
  const closeCandidatesButton = document.getElementById("close-candidates");
  if (closeCandidatesButton) {
    closeCandidatesButton.addEventListener("click", () => {
      state.candidatesOpen = false;
      render();
    });
  }
  const refreshCandidatesButton = document.getElementById("refresh-candidates");
  if (refreshCandidatesButton) refreshCandidatesButton.addEventListener("click", () => loadCandidates(true));
  const toggleTop10Button = document.getElementById("toggle-top10");
  if (toggleTop10Button) {
    toggleTop10Button.addEventListener("click", () => {
      state.top10Collapsed = !state.top10Collapsed;
      render();
    });
  }
  document.querySelectorAll("[data-toggle-section]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.toggleSection;
      state[key] = !state[key];
      render();
    });
  });
  document.querySelectorAll("[data-calc-field]").forEach((input) => {
    input.addEventListener("input", (event) => {
      const field = event.target.dataset.calcField;
      state[field] = event.target.value;
      state.calcMode = event.target.dataset.calcMode || state.calcMode;
      updateCalculatorOutput();
    });
  });
}

function goHome() {
  state.query = "";
  state.loading = false;
  state.result = null;
  state.error = "";
  state.searchCandidates = [];
  state.top10Collapsed = false;
  state.copied = false;
  state.imageCopied = false;
  state.flowImageCopied = false;
  state.imagesCopied = false;
  state.activePanel = "";
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openPanel(panel) {
  state.activePanel = state.activePanel === panel ? "" : panel;
  state.memoSaved = false;
  state.buySaved = false;
  if (panel === "buy" && state.result?.basic?.currentPrice && !state.buyPrice) {
    state.buyPrice = String(state.result.basic.currentPrice);
  }
  render();
}

function openListMemoEditor(memoId) {
  const memo = state.memos.find((item) => item.id === memoId);
  if (!memo) return;
  state.editingMemoId = memoId;
  state.editingMemoDraft = memo.note || "";
  state.memoListSaved = false;
  render();
}

function calculatorView() {
  const computed = calculateProfit();
  return `
    <div class="mini-calculator" aria-label="수익률 계산기">
      <strong>계산기</strong>
      <label>
        <span>주가</span>
        <input data-calc-field="calcPrice" data-calc-mode="${state.calcMode}" inputmode="decimal" value="${escapeHtml(state.calcPrice)}" placeholder="주가" />
      </label>
      <label>
        <span>주수</span>
        <input data-calc-field="calcQuantity" data-calc-mode="${state.calcMode}" inputmode="decimal" value="${escapeHtml(state.calcQuantity)}" placeholder="주수" />
      </label>
      <label>
        <span>수익률%</span>
        <input data-calc-field="calcReturnRate" data-calc-mode="rate" inputmode="decimal" value="${escapeHtml(state.calcReturnRate)}" placeholder="+3 / -6" />
      </label>
      <label>
        <span>주당가</span>
        <input data-calc-field="calcTargetPrice" data-calc-mode="targetPrice" inputmode="decimal" value="${escapeHtml(state.calcTargetPrice)}" placeholder="목표 주가" />
      </label>
      <label>
        <span>평가금</span>
        <input data-calc-field="calcTargetValue" data-calc-mode="targetValue" inputmode="decimal" value="${escapeHtml(state.calcTargetValue)}" placeholder="총액" />
      </label>
      <div class="calc-result">
        <span>주당 <b id="calc-target-price">${formatCalcMoney(computed.targetPrice)}</b></span>
        <span>총수익 <b id="calc-total-profit" class="${calcProfitTone(computed.totalProfit)}">${formatCalcProfit(computed.totalProfit)}</b></span>
        <span>수익률 <b id="calc-return-rate" class="${tone(computed.returnRate)}">${formatCalcRate(computed.returnRate)}</b></span>
      </div>
    </div>
  `;
}

function reportPreviewView() {
  const holdings = purchaseSummary().slice(0, 3);
  return `
    <section class="memo-list-panel report-preview-panel">
      <div class="section-head">
        <div>
          <h2>매매일지</h2>
          <p>최근 보유 종목과 매매 준비 데이터를 빠르게 확인합니다.</p>
        </div>
        <button id="open-report-preview" class="section-toggle" type="button">전체 보기</button>
      </div>
      ${holdings.length ? `
        <div class="report-preview-list">
          ${holdings.map((item) => `
            <button class="report-preview-item" data-search-ticker="${escapeHtml(item.ticker)}" type="button">
              <span>
                <strong>${escapeHtml(item.name)}</strong>
                <small>${escapeHtml(item.ticker)}</small>
              </span>
              <b>${won(item.avgPrice)}</b>
              <em>${qty(item.quantity)}</em>
              <strong>${won(item.total)}</strong>
            </button>
          `).join("")}
        </div>
      ` : `<div class="ranking-empty">보유 종목이 아직 없습니다.</div>`}
    </section>
  `;
}

function recentSearchButtonsView() {
  const fallback = [
    { ticker: "005930", name: "삼성전자" },
    { ticker: "000660", name: "SK하이닉스" },
    { ticker: "005380", name: "현대차" },
    { ticker: "035420", name: "NAVER" },
    { ticker: "373220", name: "LG에너지솔루션" },
  ];
  const items = state.recentSearches.length ? state.recentSearches : fallback;
  return items.slice(0, 6).map((item) => `
    <button class="chip" data-code="${escapeHtml(item.ticker)}" type="button">${escapeHtml(item.name || item.ticker)}</button>
  `).join("");
}

function memoListView() {
  const editingMemo = state.memos.find((memo) => memo.id === state.editingMemoId);
  const groups = groupedMemos();
  return `
    <section class="memo-list-panel">
      <div class="section-head">
        <div>
          <h2>메모한 종목</h2>
          <p>메모를 누르면 해당 메모 내용을 바로 수정합니다.</p>
        </div>
        <div class="section-actions">
          <button class="icon-add-button" data-toggle-section="memoAddOpen" type="button">+</button>
          <button class="section-toggle" data-toggle-section="memoListCollapsed" type="button">${state.memoListCollapsed ? "펼치기" : "접기"}</button>
        </div>
      </div>
      ${state.memoAddOpen ? memoAddFormView() : ""}
      ${state.memoListCollapsed ? "" : `
      ${groups.length ? `<div class="memo-list">
        ${groups.map((group) => {
          const page = Math.min(state.memoPages[group.ticker] || 0, group.memos.length - 1);
          const memo = group.memos[page];
          return `
          <div class="memo-item memo-stack ${state.editingMemoId === memo.id ? "is-active" : ""}">
            <button class="memo-main" data-edit-memo-id="${escapeHtml(memo.id)}" type="button">
              <strong>${escapeHtml(memo.name)} <span>${escapeHtml(memo.ticker)}</span></strong>
              <p>${escapeHtml(memo.note)}</p>
              <small>저장 ${formatDateTime(memo.updatedAt)}</small>
            </button>
            ${group.memos.length > 1 ? `
              <div class="memo-nav">
                <button data-memo-nav="-1" data-memo-ticker="${escapeHtml(group.ticker)}" type="button">‹</button>
                <span>${page + 1} / ${group.memos.length}</span>
                <button data-memo-nav="1" data-memo-ticker="${escapeHtml(group.ticker)}" type="button">›</button>
              </div>
            ` : ""}
          </div>
        `;
        }).join("")}
      </div>` : `<div class="ranking-empty">메모한 종목이 아직 없습니다.</div>`}
      ${editingMemo ? `
        <div class="list-memo-editor">
          <strong>${escapeHtml(editingMemo.name)} 메모 수정</strong>
          <textarea id="list-memo-draft">${escapeHtml(state.editingMemoDraft)}</textarea>
          <div class="editor-actions">
            <button id="save-list-memo" type="button">메모 저장</button>
            <button id="cancel-list-memo" type="button">닫기</button>
            <button id="delete-list-memo" class="danger-button" type="button">삭제</button>
          </div>
          ${state.memoListSaved ? `<p class="saved-message">메모가 수정되었습니다.</p>` : ""}
        </div>
      ` : ""}
      `}
    </section>
  `;
}

function groupedMemos() {
  const groups = new Map();
  for (const memo of state.memos) {
    const ticker = memo.ticker || memo.name || "memo";
    if (!groups.has(ticker)) {
      groups.set(ticker, { ticker, name: memo.name, memos: [] });
    }
    groups.get(ticker).memos.push(memo);
  }
  return Array.from(groups.values()).map((group) => ({
    ...group,
    memos: group.memos.sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || ""))),
  }));
}

function memoAddFormView() {
  return `
    <div class="inline-add-form memo-add-form">
      <input data-memo-add-field="name" value="${escapeHtml(state.memoAdd.name)}" placeholder="종목명" />
      <input data-memo-add-field="ticker" value="${escapeHtml(state.memoAdd.ticker)}" placeholder="종목코드" />
      <textarea data-memo-add-field="note" placeholder="메모">${escapeHtml(state.memoAdd.note)}</textarea>
      <button id="save-memo-add" type="button">메모 추가</button>
    </div>
  `;
}

function purchaseListView() {
  return `
    <section class="memo-list-panel">
      <div class="section-head">
        <div>
          <h2>보유 종목</h2>
          <p>보유 종목을 누르면 해당 종목을 최신 데이터로 다시 분석합니다.</p>
        </div>
        <div class="section-actions">
          <button class="icon-add-button" data-toggle-section="purchaseAddOpen" type="button">+</button>
          <button class="section-toggle" data-toggle-section="watchListCollapsed" type="button">${state.watchListCollapsed ? "펼치기" : "접기"}</button>
        </div>
      </div>
      ${state.purchaseAddOpen ? purchaseAddFormView() : ""}
      ${state.watchListCollapsed ? "" : `
      ${state.purchases.length ? `<div class="memo-list">
        ${state.purchases.slice(0, 8).map((item) => `
          <div class="memo-item purchase-item">
            <button class="purchase-main" data-search-ticker="${escapeHtml(item.ticker)}" type="button">
              <strong>${escapeHtml(item.name)} <span>${escapeHtml(item.ticker)}</span></strong>
              <p>${won(item.price)} · ${qty(item.quantity)} · 총 ${won(Number(item.price) * Number(item.quantity))}</p>
              ${holdingReturnView(item)}
              <small>구매 ${formatDateTime(item.purchasedAt)}</small>
            </button>
            <button class="delete-purchase" data-delete-purchase-id="${escapeHtml(item.id)}" type="button">삭제</button>
          </div>
        `).join("")}
      </div>` : `<div class="ranking-empty">보유 종목이 아직 없습니다.</div>`}
      `}
    </section>
  `;
}

function purchaseAddFormView() {
  return `
    <div class="inline-add-form purchase-add-form">
      <input data-purchase-add-field="name" value="${escapeHtml(state.purchaseAdd.name)}" placeholder="종목명" />
      <input data-purchase-add-field="ticker" value="${escapeHtml(state.purchaseAdd.ticker)}" placeholder="종목코드" />
      <input data-purchase-add-field="price" inputmode="decimal" value="${escapeHtml(state.purchaseAdd.price)}" placeholder="평단/매수가" />
      <input data-purchase-add-field="quantity" inputmode="numeric" value="${escapeHtml(state.purchaseAdd.quantity)}" placeholder="주수" />
      <input data-purchase-add-field="note" value="${escapeHtml(state.purchaseAdd.note)}" placeholder="댓글" />
      <button id="save-purchase-add" type="button">보유 추가</button>
    </div>
  `;
}

function holdingReturnView(item) {
  const last = state.lastPrices[item.ticker];
  if (!last?.price || !Number(item.price)) return `<p class="holding-return muted-return">최근 검색가 없음</p>`;
  const rate = ((Number(last.price) / Number(item.price)) - 1) * 100;
  return `
    <p class="holding-return ${rate >= 0 ? "holding-return-positive" : "holding-return-negative"}">
      최근 검색가 ${won(last.price)} · ${signedPercent(rate)}
    </p>
  `;
}

function candidateListView() {
  if (!state.searchCandidates.length) return "";
  return `
    <section class="memo-list-panel">
      <div class="section-head">
        <div>
          <h2>검색 후보</h2>
          <p>부분 일치 종목이 여러 개 있습니다. 분석할 종목을 선택하세요.</p>
        </div>
      </div>
      <div class="candidate-list">
        ${state.searchCandidates.map((item) => `
          <button class="candidate-item" data-search-ticker="${escapeHtml(item.ticker)}" type="button">
            <strong>${escapeHtml(item.name)}</strong>
            <span>${escapeHtml(item.ticker)} · ${escapeHtml(item.market)}</span>
          </button>
        `).join("")}
      </div>
    </section>
  `;
}

function myReportView() {
  const holdings = purchaseSummary();
  return `
    <section class="memo-list-panel report-panel wide-report-panel">
      <div class="section-head">
        <div>
          <h2>매매일지</h2>
          <p>보유 종목의 평단, 주수, 총매수금액과 매도 기록을 관리합니다.</p>
        </div>
        <button id="toggle-report-add" class="add-report-button" type="button">${state.reportAddOpen ? "추가 닫기" : "+ 추가"}</button>
      </div>
      ${state.reportAddOpen ? reportAddFormView() : ""}
      ${holdings.length ? `
        <div class="report-table">
          <div class="report-row report-head-row">
            <span>종목</span><span>평단</span><span>주수</span><span>총매수</span><span>매도 입력</span><span>예상 결과</span><span>관리</span>
          </div>
          ${holdings.map((item) => reportHoldingRow(item)).join("")}
        </div>
      ` : `<div class="ranking-empty">보유 종목이 아직 없습니다.</div>`}
      ${state.sales.length ? `
        <div class="sales-history">
          <h3>매도 기록</h3>
          ${state.sales.map((sale) => `
            <div class="sale-record">
              <strong>${escapeHtml(sale.name)} <span>${escapeHtml(sale.ticker)}</span></strong>
              <p>평단 ${won(sale.avgPrice)} · ${qty(sale.sellQuantity)} · 매도 ${won(sale.sellPrice)} · 손익 <b class="${tone(sale.profit)}">${signedWon(sale.profit)}</b> · 수익률 <b class="${tone(sale.returnRate)}">${formatCalcRate(sale.returnRate)}</b></p>
              <div class="sale-record-foot">
                <small>${formatDateTime(sale.soldAt)}</small>
                <button class="danger-button" data-delete-sale="${escapeHtml(sale.id)}" type="button">삭제</button>
              </div>
            </div>
          `).join("")}
        </div>
      ` : ""}
    </section>
  `;
}

function reportAddFormView() {
  return `
    <div class="report-add-form">
      <input data-report-add-field="name" value="${escapeHtml(state.reportAdd.name)}" placeholder="종목명" />
      <input data-report-add-field="ticker" value="${escapeHtml(state.reportAdd.ticker)}" placeholder="종목코드" />
      <input data-report-add-field="price" inputmode="decimal" value="${escapeHtml(state.reportAdd.price)}" placeholder="매수가격" />
      <input data-report-add-field="quantity" inputmode="numeric" value="${escapeHtml(state.reportAdd.quantity)}" placeholder="주수" />
      <input data-report-add-field="note" value="${escapeHtml(state.reportAdd.note)}" placeholder="댓글" />
      <button id="save-report-add" type="button">추가</button>
      ${state.reportSaved ? `<span class="saved-message">보유 종목이 추가되었습니다.</span>` : ""}
    </div>
  `;
}

function reportHoldingRow(item) {
  const input = state.saleInputs[item.ticker] || {};
  const preview = salePreview(item);
  const comment = state.reportComments[item.ticker]?.comment || "";
  const draft = state.commentDrafts[item.ticker] ?? comment;
  const commentOpen = Boolean(state.commentOpen[item.ticker]);
  const editing = state.editingPositionTicker === item.ticker;
  return `
    <div class="report-row" data-report-row="${escapeHtml(item.ticker)}">
      <span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.ticker)}</small></span>
      <span>${won(item.avgPrice)}</span>
      <span>${qty(item.quantity)}</span>
      <span>${won(item.total)}</span>
      <span class="sale-inputs">
        <input data-sale-ticker="${escapeHtml(item.ticker)}" data-sale-field="sellPrice" inputmode="decimal" value="${escapeHtml(input.sellPrice || "")}" placeholder="매도가격" />
        <input data-sale-ticker="${escapeHtml(item.ticker)}" data-sale-field="sellQuantity" inputmode="numeric" value="${escapeHtml(input.sellQuantity || "")}" placeholder="매도주수" />
        <button data-save-sale="${escapeHtml(item.ticker)}" type="button">기록</button>
      </span>
      <span class="sale-preview">
        <b id="sale-profit-${escapeHtml(item.ticker)}" class="${tone(preview.profit)}">${signedWon(preview.profit)}</b>
        <small id="sale-return-${escapeHtml(item.ticker)}" class="${tone(preview.returnRate)}">${formatCalcRate(preview.returnRate)}</small>
      </span>
      <span class="report-actions">
        <button data-toggle-comment="${escapeHtml(item.ticker)}" type="button">${commentOpen ? "댓글 접기" : "댓글"}</button>
        <button data-edit-position="${escapeHtml(item.ticker)}" type="button">수정</button>
        <button class="danger-button" data-delete-report-ticker="${escapeHtml(item.ticker)}" type="button">삭제</button>
      </span>
      ${editing ? `
        <div class="position-edit-row">
          <input data-position-field="price" inputmode="decimal" value="${escapeHtml(state.editingPositionDraft.price || "")}" placeholder="평단" />
          <input data-position-field="quantity" inputmode="numeric" value="${escapeHtml(state.editingPositionDraft.quantity || "")}" placeholder="주수" />
          <input data-position-field="note" value="${escapeHtml(state.editingPositionDraft.note || "")}" placeholder="수정 메모" />
          <button data-save-position="${escapeHtml(item.ticker)}" type="button">수정 저장</button>
          <button data-cancel-position-edit="${escapeHtml(item.ticker)}" type="button">취소</button>
        </div>
      ` : ""}
      ${commentOpen ? `
        <div class="report-comment-row">
          <textarea data-comment-field="${escapeHtml(item.ticker)}" placeholder="댓글">${escapeHtml(draft)}</textarea>
          <button data-save-comment="${escapeHtml(item.ticker)}" type="button">댓글 저장</button>
        </div>
      ` : comment ? `
        <div class="report-comment-row is-collapsed">
          <span>ㄴ ${escapeHtml(comment)}</span>
          <button class="comment-delete-button" data-delete-comment="${escapeHtml(item.ticker)}" type="button">×</button>
        </div>
      ` : ""}
    </div>
  `;
}

function rankingPanelView() {
  const rankings = state.rankings;
  const collapsed = state.top10Collapsed;
  return `
    <aside class="ranking-panel">
      <div class="section-head compact">
        <div>
          <h2>네이버 수급 Top10</h2>
          <p>항목을 누르면 최신 데이터로 자동 검색합니다.</p>
          ${rankings?.updated_at ? `<p class="ranking-meta">${escapeHtml(rankings.updated_at)} · ${escapeHtml(rankings.source || "naver_finance")}</p>` : ""}
        </div>
          <div class="top10-actions">
            <button id="toggle-top10" type="button">${collapsed ? "TOP10 펼치기" : "TOP10 접기"}</button>
            <button id="refresh-top10" type="button" ${state.rankingLoading ? "disabled" : ""}>TOP10 새로고침</button>
            <button id="open-candidates" type="button">매수 후보 찾기</button>
          </div>
        </div>
      ${favoriteButtonsView()}
      ${collapsed ? `<div class="ranking-empty">TOP10 패널이 접혀 있습니다.</div>` : `
        ${state.rankingLoading ? `<div class="ranking-loading">순위 데이터를 가져오는 중입니다.</div>` : ""}
        ${state.rankingError ? `<div class="ranking-empty">${escapeHtml(state.rankingError)}</div>` : ""}
        ${rankings ? `
          ${rankingList("외국인+기관 순매수 TOP10", rankings.combined_buy)}
          ${rankingList("외국인+기관 순매도 TOP10", rankings.combined_sell)}
          ${(!rankings.combined_buy?.length && !rankings.combined_sell?.length) ? naverRankingFramesView() : ""}
          <p class="ranking-note">${escapeHtml(rankings.note || "")}</p>
        ` : `<div class="ranking-empty">TOP10 데이터를 가져올 수 없습니다.</div>${naverRankingFramesView()}`}
      `}
    </aside>
  `;
}

function candidateModalView() {
  const payload = state.candidates;
  const items = payload?.items || [];
  return `
    <div class="candidate-modal-backdrop">
      <section class="candidate-modal">
        <div class="candidate-modal-head">
          <div>
            <h2>매수 종목 후보 Top20</h2>
            <p>
              ${payload?.updated_at ? `${escapeHtml(payload.updated_at)} 수집 · ` : ""}
              ${payload?.is_intraday ? "장중 잠정 데이터" : "마감/캐시 데이터"}
              ${payload?.universe_count ? ` · 거래대금 상위 ${payload.universe_count}개 스캔` : ""}
              ${payload?.analyzed_count ? ` · 분석 ${payload.analyzed_count}개` : ""}
            </p>
            ${payload ? `<span class="candidate-mode ${payload.selection_mode === "strict" ? "is-strict" : "is-watchlist"}">${payload.selection_mode === "strict" ? `엄격 조건 ${payload.strict_count || 0}개 통과` : "엄격 조건 없음 · 점수순 관찰 후보"}</span>` : ""}
          </div>
          <div class="candidate-modal-actions">
            <button id="refresh-candidates" type="button" ${state.candidatesLoading ? "disabled" : ""}>↻</button>
            <button id="close-candidates" type="button">닫기</button>
          </div>
        </div>
        ${state.candidatesLoading ? `<div class="ranking-loading">거래대금 상위 종목과 누적 수급을 스캔하는 중입니다. 잠시 걸릴 수 있습니다.</div>` : ""}
        ${state.candidatesError ? `<div class="ranking-empty">${escapeHtml(state.candidatesError)}</div>` : ""}
        ${items.length ? `
          <div class="candidate-result-list">
            ${items.map((item) => `
              <div class="candidate-result-item">
                <span class="candidate-result-rank">${escapeHtml(item.rank)}</span>
                <button class="candidate-result-name" data-search-ticker="${escapeHtml(item.ticker)}" type="button">
                  <strong>${escapeHtml(item.name)} <span
                    class="candidate-favorite-star ${isFavoriteTicker(item.ticker) ? "is-favorite" : ""}"
                    data-candidate-favorite="${escapeHtml(item.ticker)}"
                    data-candidate-name="${escapeHtml(item.name)}"
                    role="button"
                    tabindex="0"
                    title="${isFavoriteTicker(item.ticker) ? "즐겨찾기 취소" : "즐겨찾기"}"
                    aria-label="${isFavoriteTicker(item.ticker) ? "즐겨찾기 취소" : "즐겨찾기"}"
                  >★</span></strong>
                  <small>${escapeHtml(item.ticker)} · ${escapeHtml(item.market || "")}</small>
                </button>
                <span class="candidate-score">${escapeHtml(item.score)}점</span>
              </div>
            `).join("")}
          </div>
        ` : !state.candidatesLoading ? `<div class="ranking-empty">조건에 맞는 후보가 아직 없습니다.</div>` : ""}
        <p class="candidate-note">${escapeHtml(payload?.note || "당일 순매수만이 아니라 거래대금, 10~20일 누적 수급, 이평선, 52주 위치를 종합 점수화합니다.")}</p>
      </section>
    </div>
  `;
}

function naverRankingFramesView() {
  return `
    <div class="naver-frame-block">
      <h3>네이버 원본 순매수 화면</h3>
      <a href="https://finance.naver.com/sise/sise_deal_rank.naver" target="_blank" rel="noreferrer">외국인 순매수 열기</a>
      <a href="https://finance.naver.com/sise/sise_deal_rank.naver?investor_gubun=1000" target="_blank" rel="noreferrer">기관 순매수 열기</a>
      <iframe title="외국인 순매수" src="https://finance.naver.com/sise/sise_deal_rank_iframe.naver?sosok=01&investor_gubun=9000&type=buy"></iframe>
      <iframe title="기관 순매수" src="https://finance.naver.com/sise/sise_deal_rank_iframe.naver?sosok=01&investor_gubun=1000&type=buy"></iframe>
    </div>
  `;
}

function favoriteButtonsView() {
  if (!state.favorites.length) return "";
  return `
    <div class="favorite-block">
      <div class="favorite-head">
        <h3>즐겨찾기</h3>
        <button class="section-toggle" data-toggle-section="favoritesCollapsed" type="button">${state.favoritesCollapsed ? "펼치기" : "접기"}</button>
      </div>
      ${state.favoritesCollapsed ? "" : `
      <div class="favorite-buttons">
        ${state.favorites.map((item) => `
          <button class="favorite-chip" data-search-ticker="${escapeHtml(item.ticker)}" type="button">
            ${escapeHtml(item.name)}
          </button>
        `).join("")}
      </div>
      `}
    </div>
  `;
}

function rankingList(title, items = []) {
  if (!items.length) {
    return `
      <div class="ranking-block">
        <h3>${escapeHtml(title)}</h3>
        <div class="ranking-empty">조건에 맞는 종목이 없습니다.</div>
      </div>
    `;
  }
  return `
    <div class="ranking-block">
      <h3>${escapeHtml(title)}</h3>
      <div class="ranking-list">
        ${items.slice(0, 10).map((item, index) => `
          <button class="ranking-item" data-search-ticker="${escapeHtml(item.ticker)}" type="button">
            <span class="ranking-rank">${escapeHtml(item.rank || index + 1)}</span>
            <span class="ranking-name">
              <strong>${escapeHtml(item.name)}</strong>
              <small>${escapeHtml(item.ticker)} · ${escapeHtml(item.market || "")}${item.change_rate !== null && item.change_rate !== undefined ? ` · ${signedPercent(item.change_rate)}` : ""}</small>
            </span>
            <span class="ranking-money ${tone(item.amount ?? item.flowScore)}">${bigMoney(item.amount ?? item.flowScore)}</span>
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

function loadingView() {
  return `
    <section class="notice">
      <div class="spinner"></div>
      <div>
        <strong>pykrx와 네이버 금융 데이터를 가져오고 있습니다.</strong>
        <p>네이버 HTML 구조가 바뀌면 일부 항목은 비어 있을 수 있습니다.</p>
      </div>
    </section>
  `;
}

function emptyView() {
  if (state.loading || state.result) return "";
  return `
    <section class="empty">
      <strong>아직 분석 결과가 없습니다.</strong>
      <span>종목을 입력하면 카드 분석과 수급 캡처 이미지가 표시됩니다.</span>
    </section>
  `;
}

function resultView(result) {
  const b = result.basic;
  const ma = result.movingAverage;
  const v = result.volumeAnalysis;
  const trading = result.tradingValueAnalysis;
  const flow = result.flow;
  const week52 = result.week52;
  const breakout = result.breakout;
  const analysis = result.analysis;
  const sources = result.dataSources || {};
  const isFavorite = isFavoriteTicker(result.ticker);

  return `
    <section class="result-hero">
      <div class="result-identity">
        <div>
          <div class="stock-title-line">
            <h2>${escapeHtml(result.name)}</h2>
            <span>${escapeHtml(result.ticker)}</span>
            <button id="save-favorite" class="favorite-star ${isFavorite ? "is-favorite" : ""}" type="button" title="${isFavorite ? "즐겨찾기 취소" : "즐겨찾기"}">★</button>
          </div>
          <p>${escapeHtml(result.market || result.basic?.market || "데이터 없음")} · 업데이트 ${escapeHtml(result.updatedAt || sources.updatedAt || "")}</p>
        </div>
        <div class="hero-price">
          <strong>${won(b.currentPrice)}</strong>
          <span class="${tone(b.changeRate)}">${signedPercent(b.changeRate)}</span>
        </div>
      </div>
      <div class="status-badges">
        ${statusBadge(ma.regularAlignment, "정배열", ma.regularAlignment ? "기술적 흐름 양호" : "추세 확인 필요", "green")}
        ${statusBadge((v.volumeIncreaseRate || 0) >= 1.3, "거래량 양호", `${multiple(v.volumeIncreaseRate)} · ${v.volumeLevel || "거래량 확인"}`, "blue")}
        ${statusBadge(Boolean(trading.rank && trading.rank <= 20), "거래대금 상위", trading.rank ? `시장 상위 ${trading.rank}위` : "순위 확인 필요", "purple")}
        ${statusBadge((flow.foreign20 || 0) > 0 || (flow.institution20 || 0) > 0, "수급 체크", flow.jointStatus || "외인/기관 확인", "cyan")}
      </div>
      <div class="stock-actions hero-actions">
        <button id="open-memo" type="button" class="${state.activePanel === "memo" ? "is-active" : ""}">메모</button>
        <button id="open-buy" type="button" class="${state.activePanel === "buy" ? "is-active" : ""}">구매</button>
      </div>
    </section>

    ${state.activePanel === "memo" ? memoEditorView(result) : ""}
    ${state.activePanel === "buy" ? buyEditorView(result) : ""}

    <section class="gpt-ready-panel">
      <div>
        <h2>GPT 분석 준비 완료</h2>
        <p>텍스트와 캡처 이미지를 복사해서 ChatGPT 분석 흐름으로 바로 이동합니다.</p>
      </div>
      <div class="copy-command-grid">
        <article>
          <span>GPT용 텍스트</span>
          <p>종목 정보, 시세, 수급, 거래량 데이터가 정리된 프롬프트입니다.</p>
          <button id="copy-prompt-top" type="button">${state.copied ? "복사됨" : "GPT용 텍스트 복사"}</button>
        </article>
        <article>
          <span>네이버 차트 이미지</span>
          <p>네이버 실제 화면 기반 차트 캡처를 복사합니다.</p>
          <button id="copy-summary-image-top" type="button">${state.imageCopied ? "복사됨" : "네이버 차트 이미지 복사"}</button>
        </article>
        <article>
          <span>수급 이미지</span>
          <p>외국인/기관 수급 현황 이미지를 복사합니다.</p>
          <button id="copy-flow-image-top" type="button">${state.flowImageCopied ? "복사됨" : "수급 이미지 복사"}</button>
        </article>
      </div>
    </section>

    <details class="advanced-data">
      <summary>고급 데이터 보기</summary>
      ${sourceSummaryView(result)}
      ${result.notes?.length ? `<section class="note-list">${result.notes.map((note) => `<div>${escapeHtml(note)}</div>`).join("")}</section>` : ""}
      <section class="analysis-layout">
        <div class="analysis-main">
          <section class="dashboard-grid">
        ${card("기본 시세", [
        row("종목명", b.name),
        row("종목코드", b.ticker),
        row("시장", b.market || result.market),
        row("현재가", won(b.currentPrice)),
        row("등락률", percent(b.changeRate), tone(b.changeRate)),
        row("시가", won(b.open)),
        row("고가", won(b.high)),
        row("저가", won(b.low)),
        row("종가", won(b.close)),
        row("거래량", qty(b.volume)),
        row("시가총액", won(b.marketCap)),
      ])}
      ${card("이동평균선 분석", [
        row("MA5", won(ma.ma5)),
        row("MA20", won(ma.ma20)),
        row("MA60", won(ma.ma60)),
        row("MA120", won(ma.ma120)),
        row("현재가 > MA5", yesNo(ma.aboveMa5), ma.aboveMa5 ? "positive" : "negative"),
        row("현재가 > MA20", yesNo(ma.aboveMa20), ma.aboveMa20 ? "positive" : "negative"),
        row("현재가 > MA60", yesNo(ma.aboveMa60), ma.aboveMa60 ? "positive" : "negative"),
        row("현재가 > MA120", yesNo(ma.aboveMa120), ma.aboveMa120 ? "positive" : "negative"),
        row("정배열", yesNo(ma.regularAlignment), ma.regularAlignment ? "positive" : ""),
        row("역배열", yesNo(ma.reverseAlignment), ma.reverseAlignment ? "negative" : ""),
      ])}
      ${card("거래량 분석", [
        row("오늘 거래량", qty(v.todayVolume)),
        row("20일 평균 거래량", qty(v.averageVolume20)),
        row("거래량 증가율", multiple(v.volumeIncreaseRate)),
        row("계산 기준", v.basis),
        row("구간 해석", v.volumeLevel, volumeTone(v.volumeIncreaseRate)),
      ])}
      ${card("거래대금 분석", [
        row("거래대금", bigMoney(trading.tradingValue)),
        row("추정 거래대금", bigMoney(trading.estimatedTradingValue)),
        row("거래대금 순위", rank(trading.rank)),
        row("시장 관심도", trading.marketInterest),
        row("대차잔고", shortBalanceAmount(trading.shortBalance)),
        row("대차잔고 비중", shortBalanceRatio(trading.shortBalance)),
        row("대차잔고 해석", trading.shortBalance?.interpretation || "대차잔고 데이터를 가져올 수 없습니다."),
      ])}
      ${card("52주 위치", [
        row("52주 최고가", won(week52.high)),
        row("52주 최저가", won(week52.low)),
        row("현재가", won(week52.currentPrice)),
        row("최고가 대비", signedPercent(week52.fromHighPercent), tone(week52.fromHighPercent)),
        row("최근 60일 최고가", won(breakout.prior60High)),
        row("전고점 상태", breakout.status),
      ])}
      ${card("수급 분석", [
        row("외국인 5일", eok(flow.foreign5), tone(flow.foreign5)),
        row("외국인 20일", eok(flow.foreign20), tone(flow.foreign20)),
        row("기관 5일", eok(flow.institution5), tone(flow.institution5)),
        row("기관 20일", eok(flow.institution20), tone(flow.institution20)),
        row("외국인 보유율", percent(flow.foreignHoldingRate)),
        row("수급 상태", flow.jointStatus),
      ])}
      <article class="card summary-card">
        <h3>종합 분석</h3>
        ${summaryBlock("추세", analysis.trend)}
        ${summaryBlock("거래량", analysis.volume)}
        ${summaryBlock("수급", analysis.flow)}
        ${summaryBlock("시장관심도", analysis.marketInterest)}
        ${summaryBlock("위험요인", analysis.risk)}
        ${summaryBlock("관찰포인트", analysis.observation)}
      </article>
          </section>
        </div>
        ${summaryImagePanel(result)}
      </section>

      ${validationTableView(result)}

      ${flow.imageUrl ? `
        <section class="flow-image-panel">
          <div class="prompt-head">
            <div>
              <h3>외국인 · 기관 순매매 거래량 캡처</h3>
              <p>네이버 금융 투자자별 매매동향 표를 이미지로 저장해 표시합니다.</p>
            </div>
            <div class="image-actions">
              <button id="copy-flow-image" type="button">${state.flowImageCopied ? "복사됨" : "이미지 복사"}</button>
              <a href="${flow.imageUrl}" target="_blank" rel="noreferrer">새 창</a>
            </div>
          </div>
          <img src="${flow.imageUrl}" alt="외국인 기관 순매매 거래량" />
        </section>
      ` : ""}
    </details>

    <section class="prompt-panel">
      <div class="prompt-head">
        <div>
          <h3>GPT 분석용 프롬프트</h3>
          <p>OpenAI API를 호출하지 않습니다. 아래 내용을 복사해서 ChatGPT에 붙여넣으세요.</p>
        </div>
        <button id="copy-prompt" type="button">${state.copied ? "복사됨" : "GPT 분석용 복사"}</button>
      </div>
      <textarea readonly>${escapeHtml(result.prompt)}</textarea>
    </section>
  `;
}

function statusBadge(ok, title, detail, toneName = "blue") {
  return `
    <span class="status-card ${ok ? "is-good" : "is-neutral"} status-${escapeHtml(toneName)}">
      <b>${escapeHtml(title)}</b>
      <small>${escapeHtml(detail)}</small>
    </span>
  `;
}

function memoEditorView(result) {
  const stockMemos = state.memos.filter((memo) => memo.ticker === result.ticker);
  const selectedMemo = stockMemos.find((memo) => memo.id === state.selectedMemoId) || stockMemos[0];
  return `
    <section class="quick-editor">
      <div class="section-head">
        <div>
          <h2>${escapeHtml(result.name)} 메모</h2>
          <p>메모를 여러 개 저장하고 날짜를 눌러 다시 볼 수 있습니다.</p>
        </div>
      </div>
      ${stockMemos.length ? `
        <div class="memo-history">
          ${stockMemos.map((memo) => `
            <button class="${selectedMemo?.id === memo.id ? "is-active" : ""}" data-memo-id="${escapeHtml(memo.id)}" type="button">
              ${formatDateTime(memo.updatedAt)}
            </button>
          `).join("")}
        </div>
      ` : ""}
      ${selectedMemo ? `
        <div class="selected-memo">
          <div>
            <strong>${formatDateTime(selectedMemo.updatedAt)}</strong>
            <p>${escapeHtml(selectedMemo.note)}</p>
          </div>
          <button id="delete-memo" type="button">삭제</button>
        </div>
      ` : ""}
      <textarea id="memo-draft" placeholder="가볍게 관찰 내용을 적어두세요.">${escapeHtml(state.memoDraft)}</textarea>
      <div class="editor-actions">
        <button id="save-memo" type="button">새 메모 저장</button>
        ${state.memoSaved ? `<span>저장 ${formatDateTime(new Date().toISOString())}</span>` : ""}
      </div>
    </section>
  `;
}

function buyEditorView(result) {
  return `
    <section class="quick-editor">
      <div class="section-head">
        <div>
          <h2>${escapeHtml(result.name)} 구매 기록</h2>
          <p>저장하면 관심종목 / 구매 기록에 올라가고 구매 시간이 함께 남습니다.</p>
        </div>
      </div>
      <div class="buy-grid">
        <label>
          <span>구매 가격</span>
          <input id="buy-price" inputmode="numeric" value="${escapeHtml(state.buyPrice)}" placeholder="예: 60400" />
        </label>
        <label>
          <span>수량</span>
          <input id="buy-quantity" inputmode="numeric" value="${escapeHtml(state.buyQuantity)}" placeholder="예: 10" />
        </label>
      </div>
      <textarea id="buy-note" placeholder="구매 이유나 관찰 포인트">${escapeHtml(state.buyNote)}</textarea>
      <div class="editor-actions">
        <button id="save-buy" type="button">관심종목에 추가</button>
        ${state.buySaved ? `<span>구매 기록을 저장했습니다.</span>` : ""}
      </div>
    </section>
  `;
}

function sourceSummaryView(result) {
  const sources = result.dataSources || {};
  return `
    <section class="source-panel">
      <div class="source-grid">
        <div><span>현재가/거래량</span><strong>${escapeHtml(sources.quote || "데이터 없음")}</strong></div>
        <div><span>일봉 OHLCV</span><strong>${escapeHtml(sources.ohlcv || "데이터 없음")}</strong></div>
        <div><span>이동평균선</span><strong>${escapeHtml(sources.movingAverage || "데이터 없음")}</strong></div>
        <div><span>거래대금</span><strong>${escapeHtml(sources.tradingValue || "데이터 없음")}</strong></div>
        <div><span>수급</span><strong>${escapeHtml(sources.supply || "데이터 없음")}</strong></div>
        <div><span>종목 검색</span><strong>${escapeHtml(searchSourceLabel(result.searchSource))}</strong></div>
        <div><span>상태</span><strong>${result.isIntraday ? "장중 잠정 데이터" : "종가/마감 데이터"}</strong></div>
      </div>
      <p>NXT 포함/네이버 시세와 KRX 정규장 시세는 다를 수 있습니다. MA5/20/60/120은 pykrx KRX 일봉 종가 기준이며 장중 현재가는 MA 계산에 넣지 않습니다.</p>
    </section>
  `;
}

function validationTableView(result) {
  const rows = result.validation?.rows || [];
  if (!rows.length) return "";
  return `
    <section class="validation-panel">
      <div class="section-head">
        <div>
          <h2>데이터 검증표</h2>
          <p>${escapeHtml(result.validation?.notice || "")}</p>
        </div>
      </div>
      <div class="validation-table-wrap">
        <table class="validation-table">
          <thead>
            <tr>
              <th>항목</th>
              <th>원본값</th>
              <th>표시/변환값</th>
              <th>출처</th>
              <th>업데이트</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((row) => `
              <tr>
                <td>${escapeHtml(row.label)}</td>
                <td>${escapeHtml(formatRawDebug(row.raw))}</td>
                <td>${escapeHtml(formatDebugValue(row.label, row.converted))}</td>
                <td>${escapeHtml(row.source)}</td>
                <td>${escapeHtml(row.updatedAt)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function card(title, rows) {
  return `
    <article class="card">
      <h3>${escapeHtml(title)}</h3>
      <div class="metric-list">${rows.join("")}</div>
    </article>
  `;
}

function row(label, value, valueClass = "") {
  return `
    <div class="metric-row">
      <span>${escapeHtml(label)}</span>
      <strong class="${valueClass}">${escapeHtml(value ?? "데이터 없음")}</strong>
    </div>
  `;
}

function summaryBlock(label, text) {
  return `
    <div class="summary-block">
      <span>[${escapeHtml(label)}]</span>
      <p>${escapeHtml(text)}</p>
    </div>
  `;
}

function summaryImagePanel(result) {
  if (!result.summaryImageUrl) {
    return `
      <aside class="summary-image-panel">
        <h3>네이버식 요약 캡처</h3>
        <div class="empty-image">캡처 이미지를 만들 수 없습니다.</div>
      </aside>
    `;
  }
  return `
    <aside class="summary-image-panel">
      <div class="prompt-head">
        <div>
          <h3>네이버식 요약 캡처</h3>
          <p>네이버 화면 형식으로 주요 시세, 차트, 수급을 이미지로 정리했습니다.</p>
        </div>
        <button id="copy-summary-image" type="button">${state.imageCopied ? "복사됨" : "이미지 복사"}</button>
      </div>
      <img src="${result.summaryImageUrl}" alt="네이버식 종목 요약 캡처" />
    </aside>
  `;
}

async function analyze(event) {
  event.preventDefault();
  const query = document.getElementById("query").value.trim();
  await analyzeByQuery(query);
}

async function analyzeByQuery(query) {
  if (!query) {
    state.error = "종목명 또는 종목코드를 입력해 주세요.";
    render();
    return;
  }

  state.query = query;
  state.loading = true;
  state.result = null;
  state.error = "";
  state.top10Collapsed = true;
  state.copied = false;
  state.activePanel = "";
  state.memoDraft = "";
  state.selectedMemoId = "";
  state.memoSaved = false;
  state.buyPrice = "";
  state.buyQuantity = "";
  state.buyNote = "";
  state.buySaved = false;
  state.imageCopied = false;
  state.flowImageCopied = false;
  state.imagesCopied = false;
  render();

  try {
    const response = await fetch(apiUrl("/api/analyze"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, quoteMode: state.quoteMode }),
    });
    const payload = await response.json();
    if (!response.ok) {
      state.searchCandidates = payload.candidates || [];
      throw new Error(payload.error || "분석에 실패했습니다.");
    }
    await loadFavorites();
    state.result = payload;
    rememberSearch(payload);
    const memo = state.memos.find((item) => item.ticker === payload.ticker);
    state.selectedMemoId = memo?.id || "";
    state.memoDraft = "";
    state.buyPrice = payload.basic?.currentPrice ? String(payload.basic.currentPrice) : "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.loading = false;
    render();
    if (state.result) {
      setTimeout(() => {
        document.querySelector(".result-hero")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 50);
    }
  }
}

function rememberSearch(result) {
  if (!result?.ticker) return;
  state.recentSearches = [
    { ticker: result.ticker, name: result.name || result.ticker },
    ...state.recentSearches.filter((item) => item.ticker !== result.ticker),
  ].slice(0, 8);
  saveLocalJson("junsu_recent_searches", state.recentSearches);
  if (result.basic?.currentPrice) {
    state.lastPrices = {
      ...state.lastPrices,
      [result.ticker]: {
        price: result.basic.currentPrice,
        name: result.name || result.ticker,
        updatedAt: result.updatedAt || new Date().toISOString(),
      },
    };
    saveLocalJson("junsu_last_prices", state.lastPrices);
  }
}

async function saveMemo() {
  if (!state.result) return;
  try {
    const response = await fetch(apiUrl("/api/memos"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: state.result.ticker,
        name: state.result.name,
        note: state.memoDraft,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "메모 저장에 실패했습니다.");
    state.memos = payload;
    const latest = payload.find((item) => item.ticker === state.result.ticker);
    state.selectedMemoId = latest?.id || "";
    state.memoDraft = "";
    state.memoSaved = true;
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function saveListMemo() {
  if (!state.editingMemoId) return;
  try {
    const response = await fetch(apiUrl(`/api/memos/${encodeURIComponent(state.editingMemoId)}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: state.editingMemoDraft }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "메모 수정에 실패했습니다.");
    state.memos = payload;
    const current = payload.find((item) => item.id === state.editingMemoId);
    state.editingMemoDraft = current?.note || "";
    state.memoListSaved = true;
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function saveMemoAdd() {
  try {
    const response = await fetch(apiUrl("/api/memos"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: state.memoAdd.ticker,
        name: state.memoAdd.name,
        note: state.memoAdd.note,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "메모 추가에 실패했습니다.");
    state.memos = payload;
    state.memoAdd = { ticker: "", name: "", note: "" };
    state.memoAddOpen = false;
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function deleteListMemo() {
  if (!state.editingMemoId) return;
  try {
    const response = await fetch(apiUrl(`/api/memos/${encodeURIComponent(state.editingMemoId)}`), {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "메모 삭제에 실패했습니다.");
    state.memos = payload;
    state.editingMemoId = "";
    state.editingMemoDraft = "";
    state.memoListSaved = false;
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function deleteSelectedMemo() {
  if (!state.selectedMemoId) return;
  try {
    const response = await fetch(apiUrl(`/api/memos/${encodeURIComponent(state.selectedMemoId)}`), {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "메모 삭제에 실패했습니다.");
    state.memos = payload;
    const latest = payload.find((item) => item.ticker === state.result?.ticker);
    state.selectedMemoId = latest?.id || "";
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function saveFavorite() {
  if (!state.result) return;
  await toggleFavoriteItem({
    ticker: state.result.ticker,
    name: state.result.name,
  });
}

async function toggleFavoriteItem(item) {
  if (!item?.ticker) return;
  try {
    const ticker = normalizeTicker(item.ticker);
    const isFavorite = isFavoriteTicker(ticker);
    const response = isFavorite
      ? await fetch(apiUrl(`/api/favorites/${encodeURIComponent(ticker)}`), { method: "DELETE" })
      : await fetch(apiUrl("/api/favorites"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ticker,
            name: item.name || ticker,
          }),
        });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "즐겨찾기 변경에 실패했습니다.");
    state.favorites = payload;
    await loadFavorites();
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function savePurchase() {
  if (!state.result) return;
  try {
    const response = await fetch(apiUrl("/api/purchases"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: state.result.ticker,
        name: state.result.name,
        price: numberOnly(state.buyPrice),
        quantity: numberOnly(state.buyQuantity),
        note: state.buyNote,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "구매 기록 저장에 실패했습니다.");
    state.purchases = payload;
    await loadFavorites();
    state.buySaved = true;
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function deletePurchase(purchaseId) {
  if (!purchaseId) return;
  try {
    const response = await fetch(apiUrl(`/api/purchases/${encodeURIComponent(purchaseId)}`), {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "구매 기록 삭제에 실패했습니다.");
    state.purchases = payload;
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function saveReportPurchase() {
  try {
    const response = await fetch(apiUrl("/api/purchases"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: state.reportAdd.ticker,
        name: state.reportAdd.name,
        price: numberOnly(state.reportAdd.price),
        quantity: numberOnly(state.reportAdd.quantity),
        note: state.reportAdd.note,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "보유 종목 추가에 실패했습니다.");
    state.purchases = payload;
    await loadFavorites();
    state.reportAdd = { ticker: "", name: "", price: "", quantity: "", note: "" };
    state.reportSaved = true;
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function savePurchaseAdd() {
  try {
    const response = await fetch(apiUrl("/api/purchases"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: state.purchaseAdd.ticker,
        name: state.purchaseAdd.name,
        price: numberOnly(state.purchaseAdd.price),
        quantity: numberOnly(state.purchaseAdd.quantity),
        note: state.purchaseAdd.note,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "보유 종목 추가에 실패했습니다.");
    state.purchases = payload;
    await loadFavorites();
    state.purchaseAdd = { ticker: "", name: "", price: "", quantity: "", note: "" };
    state.purchaseAddOpen = false;
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function deleteReportTicker(ticker) {
  if (!ticker) return;
  try {
    const response = await fetch(apiUrl(`/api/purchases/by-ticker/${encodeURIComponent(ticker)}`), {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "보유 종목 삭제에 실패했습니다.");
    state.purchases = payload;
    delete state.saleInputs[ticker];
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

function openPositionEditor(ticker) {
  const item = purchaseSummary().find((holding) => holding.ticker === ticker);
  if (!item) return;
  state.editingPositionTicker = ticker;
  state.editingPositionDraft = {
    name: item.name,
    price: String(Math.round(item.avgPrice)),
    quantity: String(item.quantity),
    note: state.reportComments[ticker]?.comment || "",
  };
  render();
}

async function savePositionEdit(ticker) {
  const item = purchaseSummary().find((holding) => holding.ticker === ticker);
  const draft = state.editingPositionDraft;
  if (!item) return;
  try {
    const response = await fetch(apiUrl(`/api/purchases/by-ticker/${encodeURIComponent(ticker)}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker,
        name: item.name,
        price: numberOnly(draft.price),
        quantity: numberOnly(draft.quantity),
        note: draft.note || "",
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "보유 종목 수정에 실패했습니다.");
    state.purchases = payload;
    state.editingPositionTicker = "";
    state.editingPositionDraft = {};
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function saveReportComment(ticker) {
  try {
    const response = await fetch(apiUrl(`/api/report-comments/${encodeURIComponent(ticker)}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment: state.commentDrafts[ticker] || "" }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "댓글 저장에 실패했습니다.");
    state.reportComments = payload;
    state.commentOpen[ticker] = false;
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function deleteReportComment(ticker) {
  state.commentDrafts[ticker] = "";
  await saveReportComment(ticker);
}

async function deleteSale(saleId) {
  if (!saleId) return;
  try {
    const response = await fetch(apiUrl(`/api/sales/${encodeURIComponent(saleId)}`), {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "매도 기록 삭제에 실패했습니다.");
    state.sales = payload;
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function saveSale(ticker) {
  const item = purchaseSummary().find((holding) => holding.ticker === ticker);
  const input = state.saleInputs[ticker] || {};
  if (!item) return;
  try {
    const response = await fetch(apiUrl("/api/sales"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: item.ticker,
        name: item.name,
        avgPrice: item.avgPrice,
        buyQuantity: item.quantity,
        sellPrice: numberOnly(input.sellPrice),
        sellQuantity: numberOnly(input.sellQuantity),
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "매도 기록 저장에 실패했습니다.");
    state.sales = payload;
    state.saleInputs[ticker] = {};
    render();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function copyPrompt() {
  if (!state.result?.prompt) return;
  const plainText = buildClipboardPlainText(state.result);
  const html = await buildClipboardHtml(state.result);
  try {
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/plain": new Blob([plainText], { type: "text/plain" }),
        "text/html": new Blob([html], { type: "text/html" }),
      }),
    ]);
  } catch (error) {
    try {
      copyHtmlWithSelection(html, plainText);
    } catch (fallbackError) {
      await navigator.clipboard.writeText(plainText);
    }
  } finally {
    state.copied = true;
    render();
  }
}

async function copySummaryImage() {
  const url = state.result?.summaryImageUrl;
  if (!url) return;
  const copied = await copyImageUrl(url);
  if (copied) {
    state.imageCopied = true;
    render();
  }
}

async function copyFlowImage() {
  const url = state.result?.flow?.imageUrl;
  if (!url) return;
  const copied = await copyImageUrl(url);
  if (copied) {
    state.flowImageCopied = true;
    render();
  }
}

async function copyImageUrl(url) {
  try {
    const pngBlob = await fetchImageAsPng(url);
    await navigator.clipboard.write([new ClipboardItem({ "image/png": pngBlob })]);
    return true;
  } catch (error) {
    window.open(resourceUrl(url), "_blank", "noopener,noreferrer");
    return false;
  }
}

async function fetchImageAsPng(url) {
  const response = await fetch(resourceUrl(url));
  if (!response.ok) throw new Error("이미지를 불러올 수 없습니다.");
  const blob = await response.blob();
  return blob.type === "image/png" ? blob : await convertImageBlobToPng(blob);
}

async function convertImageBlobToPng(blob) {
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const context = canvas.getContext("2d");
  context.drawImage(bitmap, 0, 0);
  return await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

async function buildImagesClipboardHtml(images) {
  const blocks = [];
  for (const image of images) {
    const src = await safeImageToDataUrl(image.url);
    blocks.push(`<h3>${escapeHtml(image.title)}</h3>${imageHtml(src, image.title)}`);
  }
  return `<div style="font-family:Arial,'Noto Sans KR',sans-serif;">${blocks.join("<br />")}</div>`;
}

function buildClipboardPlainText(result) {
  const labels = [];
  if (result.summaryImageUrl) labels.push("네이버식 요약 캡처 포함");
  if (result.flow?.imageUrl) labels.push("외국인/기관 순매매거래량 캡처 포함");
  if (!labels.length) return result.prompt;
  return `${result.prompt}\n\n첨부 이미지: ${labels.join(", ")}`;
}

async function buildClipboardHtml(result) {
  const blocks = [`<pre style="white-space:pre-wrap;font-family:Arial,'Noto Sans KR',sans-serif;font-size:14px;line-height:1.5;">${escapeHtml(result.prompt)}</pre>`];
  if (result.summaryImageUrl) {
    const src = await safeImageToDataUrl(result.summaryImageUrl);
    blocks.push(`<h3>네이버식 요약 캡처</h3>${imageHtml(src, "네이버식 요약 캡처")}`);
  }
  if (result.flow?.imageUrl) {
    const src = await safeImageToDataUrl(result.flow.imageUrl);
    blocks.push(`<h3>외국인 / 기관 순매매거래량 캡처</h3>${imageHtml(src, "외국인 기관 순매매거래량 캡처")}`);
  }
  return `<div style="font-family:Arial,'Noto Sans KR',sans-serif;">${blocks.join("<br />")}</div>`;
}

function imageHtml(src, alt) {
  if (!src) return `<p>${escapeHtml(alt)} 이미지를 불러오지 못했습니다.</p>`;
  return `<img src="${src}" alt="${escapeHtml(alt)}" style="display:block;max-width:100%;height:auto;margin:8px 0 18px;" />`;
}

async function safeImageToDataUrl(url) {
  try {
    return await imageToDataUrl(url);
  } catch (error) {
    return "";
  }
}

async function imageToDataUrl(url) {
  const response = await fetch(resourceUrl(url));
  if (!response.ok) throw new Error("이미지를 불러올 수 없습니다.");
  const blob = await response.blob();
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

function copyHtmlWithSelection(html, plainText) {
  const container = document.createElement("div");
  container.contentEditable = "true";
  container.style.position = "fixed";
  container.style.left = "-10000px";
  container.style.top = "0";
  container.innerHTML = html;
  document.body.appendChild(container);

  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(container);
  selection.removeAllRanges();
  selection.addRange(range);

  const listener = (event) => {
    event.clipboardData.setData("text/html", html);
    event.clipboardData.setData("text/plain", plainText);
    event.preventDefault();
  };
  document.addEventListener("copy", listener, { once: true });
  const ok = document.execCommand("copy");
  selection.removeAllRanges();
  container.remove();
  if (!ok) throw new Error("복사에 실패했습니다.");
}

function won(value) {
  if (value === null || value === undefined || value === "") return "데이터 없음";
  return `${Number(value).toLocaleString("ko-KR")}원`;
}

function qty(value) {
  if (value === null || value === undefined || value === "") return "데이터 없음";
  return `${Number(value).toLocaleString("ko-KR")}주`;
}

function eok(value) {
  if (value === null || value === undefined) return "데이터 없음";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Math.round(Number(value) / 100000000).toLocaleString("ko-KR")}억`;
}

function percent(value) {
  if (value === null || value === undefined) return "데이터 없음";
  return `${Number(value).toFixed(2)}%`;
}

function signedPercent(value) {
  if (value === null || value === undefined) return "데이터 없음";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

function multiple(value) {
  if (value === null || value === undefined) return "데이터 없음";
  return `${Number(value).toFixed(2)}배`;
}

function bigMoney(value) {
  if (value === null || value === undefined) return "데이터 없음";
  const eokValue = Number(value) / 100000000;
  if (Math.abs(eokValue) >= 1000) return `${(eokValue / 1000).toFixed(2)}천억 원`;
  return `${Math.round(eokValue).toLocaleString("ko-KR")}억 원`;
}

function shortBalanceAmount(shortBalance) {
  if (!shortBalance?.available) return "데이터 없음";
  const balance = shortBalance.balance === null || shortBalance.balance === undefined ? "-" : `${Number(shortBalance.balance).toLocaleString("ko-KR")}주`;
  const amount = shortBalance.amount ? ` · ${bigMoney(shortBalance.amount)}` : "";
  return `${balance}${amount}`;
}

function shortBalanceRatio(shortBalance) {
  if (!shortBalance?.available || shortBalance.ratio === null || shortBalance.ratio === undefined) return "데이터 없음";
  const change = shortBalance.change5 === null || shortBalance.change5 === undefined ? "" : ` · 5일 ${Number(shortBalance.change5).toLocaleString("ko-KR")}주`;
  return `${Number(shortBalance.ratio).toFixed(2)}%${change}`;
}

function searchSourceLabel(source) {
  if (source === "pykrx") return "pykrx 종목 DB";
  if (source === "naver_fallback") return "네이버 금융 검색 fallback";
  if (source === "cache") return "종목 검색 캐시";
  return "데이터 없음";
}

function formatRawDebug(value) {
  if (value === null || value === undefined || value === "") return "데이터 없음";
  if (typeof value === "number") return Number(value).toLocaleString("ko-KR");
  return String(value);
}

function formatDebugValue(label, value) {
  if (value === null || value === undefined || value === "") return "데이터 없음";
  if (String(label).includes("거래대금")) return `${Number(value).toLocaleString("ko-KR")}원 (${bigMoney(value)})`;
  if (String(label).includes("거래량")) return qty(value);
  if (String(label).includes("현재가") || String(label).includes("종가") || String(label).startsWith("MA")) return won(value);
  return Number(value).toLocaleString("ko-KR");
}

function rank(value) {
  if (value === null || value === undefined) return "데이터 없음";
  return `${value}위`;
}

function yesNo(value) {
  if (value === null || value === undefined) return "데이터 없음";
  return value ? "예" : "아니오";
}

function tone(value) {
  if (value === null || value === undefined) return "";
  if (Number(value) > 0) return "positive";
  if (Number(value) < 0) return "negative";
  return "";
}

function volumeTone(value) {
  if (value === null || value === undefined) return "";
  if (Number(value) >= 2) return "positive";
  if (Number(value) < 1) return "muted-value";
  return "";
}

function formatDateTime(value) {
  if (!value) return "";
  return value.replace("T", " ").slice(0, 19);
}

function numberOnly(value) {
  return String(value || "").replace(/[^\d.]/g, "");
}

function parseCalcNumber(value) {
  const cleaned = String(value || "").replace(/,/g, "").trim();
  if (!cleaned) return null;
  const number = Number(cleaned);
  return Number.isFinite(number) ? number : null;
}

function calculateProfit() {
  const price = parseCalcNumber(state.calcPrice);
  const quantity = parseCalcNumber(state.calcQuantity);
  const rate = parseCalcNumber(state.calcReturnRate);
  const targetPriceInput = parseCalcNumber(state.calcTargetPrice);
  const targetValueInput = parseCalcNumber(state.calcTargetValue);
  let targetPrice = null;
  let targetValue = null;
  let returnRate = null;
  let totalProfit = null;

  if (state.calcMode === "targetValue" && price && quantity && targetValueInput !== null) {
    targetValue = targetValueInput;
    targetPrice = targetValue / quantity;
    returnRate = ((targetPrice / price) - 1) * 100;
  } else if (state.calcMode === "targetPrice" && price && targetPriceInput !== null) {
    targetPrice = targetPriceInput;
    targetValue = quantity ? targetPrice * quantity : null;
    returnRate = ((targetPrice / price) - 1) * 100;
  } else if (price && rate !== null) {
    targetPrice = price * (1 + rate / 100);
    targetValue = quantity ? targetPrice * quantity : null;
    returnRate = rate;
  } else if (price && targetPriceInput !== null) {
    targetPrice = targetPriceInput;
    targetValue = quantity ? targetPrice * quantity : null;
    returnRate = ((targetPrice / price) - 1) * 100;
  } else if (price && quantity && targetValueInput !== null) {
    targetValue = targetValueInput;
    targetPrice = targetValue / quantity;
    returnRate = ((targetPrice / price) - 1) * 100;
  }

  if (price && quantity && targetPrice !== null && targetPrice !== undefined) {
    totalProfit = (targetPrice - price) * quantity;
  }

  return { targetPrice, targetValue, returnRate, totalProfit };
}

function purchaseSummary() {
  const grouped = new Map();
  for (const purchase of state.purchases) {
    const ticker = purchase.ticker;
    const price = Number(purchase.price) || 0;
    const quantity = Number(purchase.quantity) || 0;
    if (!ticker || price <= 0 || quantity <= 0) continue;
    const item = grouped.get(ticker) || {
      ticker,
      name: purchase.name,
      quantity: 0,
      total: 0,
      avgPrice: 0,
    };
    item.quantity += quantity;
    item.total += price * quantity;
    item.avgPrice = item.quantity ? item.total / item.quantity : 0;
    grouped.set(ticker, item);
  }
  return Array.from(grouped.values()).sort((a, b) => b.total - a.total);
}

function normalizeTicker(value) {
  const text = String(value ?? "").trim();
  return /^\d+$/.test(text) ? text.padStart(6, "0") : text;
}

function isFavoriteTicker(ticker) {
  const target = normalizeTicker(ticker);
  return state.favorites.some((item) => normalizeTicker(item.ticker) === target);
}

function salePreview(item) {
  const input = state.saleInputs[item.ticker] || {};
  const sellPrice = parseCalcNumber(input.sellPrice);
  const sellQuantity = parseCalcNumber(input.sellQuantity);
  if (!sellPrice || !sellQuantity || !item.avgPrice) {
    return { profit: null, returnRate: null };
  }
  const profit = (sellPrice - item.avgPrice) * sellQuantity;
  const returnRate = profit / (item.avgPrice * sellQuantity) * 100;
  return { profit, returnRate };
}

function updateReportSalePreview(ticker) {
  const item = purchaseSummary().find((holding) => holding.ticker === ticker);
  if (!item) return;
  const preview = salePreview(item);
  const profit = document.getElementById(`sale-profit-${ticker}`);
  const returnRate = document.getElementById(`sale-return-${ticker}`);
  if (profit) {
    profit.textContent = signedWon(preview.profit);
    profit.className = tone(preview.profit);
  }
  if (returnRate) {
    returnRate.textContent = formatCalcRate(preview.returnRate);
    returnRate.className = tone(preview.returnRate);
  }
}

function updateCalculatorOutput() {
  const computed = calculateProfit();
  const targetPrice = document.getElementById("calc-target-price");
  const totalProfit = document.getElementById("calc-total-profit");
  const returnRate = document.getElementById("calc-return-rate");
  if (targetPrice) targetPrice.textContent = formatCalcMoney(computed.targetPrice);
  if (totalProfit) {
    totalProfit.textContent = formatCalcProfit(computed.totalProfit);
    totalProfit.className = calcProfitTone(computed.totalProfit);
  }
  if (returnRate) {
    returnRate.textContent = formatCalcRate(computed.returnRate);
    returnRate.className = tone(computed.returnRate);
  }
}

function formatCalcMoney(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "-";
  return Math.round(Number(value)).toLocaleString("ko-KR");
}

function formatCalcRate(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "-";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

function formatCalcProfit(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "-";
  const amount = Number(value);
  const manWon = Math.trunc(Math.abs(amount) / 10000);
  if (manWon === 0) return "0만원";
  const sign = amount > 0 ? "+" : "-";
  return `${sign}${manWon.toLocaleString("ko-KR")}만원`;
}

function calcProfitTone(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value)) || Number(value) === 0) return "";
  return Number(value) > 0 ? "calc-profit-positive" : "calc-profit-negative";
}

function signedWon(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "-";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Math.round(Number(value)).toLocaleString("ko-KR")}원`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

init();
