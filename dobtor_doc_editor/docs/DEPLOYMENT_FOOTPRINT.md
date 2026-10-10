# 部署足跡：`git pull` 會送到正式機的東西

**回答的問題**：這兩個模組部署到正式機時，到底帶了多少東西下去，哪些是正式機
用不到的，排掉它要注意什麼。

部署方式是 **docker + github pull + PaaS**。這一點決定了整份文件的前提：

- **打包腳本沒用。** 沒有 `git archive`／tarball 這一層，所以 `.gitattributes`
  的 `export-ignore` 也**沒用**——那個旗標只對 `git archive` 有效，對 `clone`
  與 `pull` 完全無效。
- **`git pull` 會帶下每一個追蹤檔案。** 排除只能發生在**部署端**（容器的
  clone／pull 腳本），不在這個 repo 裡。本文件最後一節給兩種寫法。

## 1. 實測數字

量法是 `git archive HEAD dobtor_doc_editor dobtor_doc_import | tar -x`
——**攤的是 HEAD 的追蹤檔案**，也就是 `git pull` 真正會送到正式機的那一份。
（不是 `rsync` 工作樹。工作樹會把 `node_modules` 這類未追蹤的東西一起算進去，
量到的就不是部署足跡。）重現：`tests/scripts/run_ships_without_tests_check.sh`

| 項目 | 大小 | 檔案數 | 會跟著 `git pull` 嗎 |
|---|---|---|---|
| 兩個模組的追蹤檔案合計 | **94.4 MB** | 1,144 | — |
| ├ `dobtor_doc_editor` | 6.3 MB | 179 | 會 |
| └ `dobtor_doc_import` | 88.1 MB | 965 | 會 |
| `dobtor_doc_import/tests/` | **84.7 MB** | 757 | **會** |
| └ 其中 `tests/fixtures/` | **82.2 MB** | — | **會** |
| `dobtor_doc_editor/tests/` | 0.7 MB | 49 | 會 |
| `dobtor_doc_editor/static/tests/` | 28 KB | 1 | 會（**要留**，見陷阱一） |
| `dobtor_doc_import/node_modules/` | 120.6 MB | — | 不會（未追蹤） |
| `tests/fixtures/.visual_regression_tmp/` | ~52 MB | — | 不會（已 ignore） |

**排掉兩個模組的 `tests/` 之後：94.4 MB → 9.0 MB，每一台正式機省 85.4 MB。**

### 不會旅行但會長的那兩個

`node_modules`（120.6 MB）與 `.visual_regression_tmp`（~52 MB）都不會跟著
`git pull`，所以它們不是部署問題——但它們在**開發機**上只會長不會縮。
`.visual_regression_tmp` 到 2026-10-10 之前**沒有任何 clean target 清它**
（`dobtor_doc_import/Makefile` 的 `.PHONY` 甚至宣告了一個不存在的 `clean`）。
現在有了：

```bash
cd dobtor_doc_import && make clean      # clean-build ＋ clean-vr
cd dobtor_doc_import && make clean-vr   # 只清 VR 中間影像
```

## 2. 排掉 `tests/` 的前提已經驗過了

排除規則成立的前提是**出貨程式不依賴 `tests/`**。這件事「看起來成立」不算——
所以它變成完工判準 `ships-without-tests`
（見 [`DONE_CRITERIA.md`](DONE_CRITERIA.md)），每次 `make done` 都會重驗一次：

1. `git archive HEAD` 攤出追蹤檔案
2. 刪掉兩個模組的 `tests/`
3. 確認 `static/tests/tours/*.js` **還在**（陷阱一的守衛）
4. 用**只指向探針目錄**的 addons-path 裝進乾淨 DB
5. 斷言兩個模組都 `installed`

2026-10-10 的結果：`96672 KB → 9180 KB`，兩個模組都 `installed`。

**負向控制**（證明這支腳本抓得到東西，不是永遠綠）：在探針的
`dobtor_doc_editor/models/__init__.py` 末尾加一行
`from ..tests import session_probe`，同一條安裝指令的結果是

```
dobtor_doc_editor = uninstalled
dobtor_doc_import = uninstalled
ModuleNotFoundError: No module named 'odoo.addons.dobtor_doc_editor.tests'
```

順手量過的三件事（都是「為什麼前提成立」的依據，不必再驗一遍）：

- 兩模組的 `models/`、`controllers/`、`wizards/`、`tools/` 裡**沒有任何一處**
  `import` `tests/`。
- 兩模組 manifest 的 `data` 清單**沒有一條**指向 `tests/`。
- manifest 裡唯一指向測試路徑的是核心的
  `web.assets_tests: ['dobtor_doc_editor/static/tests/tours/*.js']`
  ——而 `web.assets_tests` 這個 bundle **只在測試模式下建**，正式機不碰它。

## 3. 兩個陷阱

### 陷阱一：`tests/` 這個樣式會把 `static/tests/` 一起排掉

`rsync --exclude='tests/'`、`tar --exclude='tests'`、`.dockerignore` 的
`tests/` 都是**樣式匹配任何層級**，所以 `static/tests/` 也中。
而 `static/tests/tours/*.js` 在 manifest 的 `web.assets_tests` bundle 裡
——被排掉就是一個指向不存在檔案的 asset 宣告。

**排除樣式必須錨定到模組根**：

```
/dobtor_doc_editor/tests/
/dobtor_doc_import/tests/
```

`run_ships_without_tests_check.sh` 的第 3 步就是守這一條：探針裡
`static/tests/tours/*.js` 不見了就直接紅，不等到安裝。

### 陷阱二：`git sparse-checkout` 要 git 2.25+，而這台 host 是 2.19.1

正式機容器裡的 git 版本**未知**（這台 host 看不到正式機；順帶一提
`qcodoo` 這個 odoo:18 映像**根本沒裝 git**，所以 pull 一定發生在別處）。
兩種寫法都列在這裡，用之前先 `git --version`：

**git 2.25+（有 `sparse-checkout` 子命令）** —— ☠️ **這台 host 是 2.19，
所以下面這段沒有實測過**，用之前請在目標機器上先跑一次，並做下面那條 `ls` 檢查。

```bash
git clone --filter=blob:none --no-checkout <repo> addons
cd addons
git sparse-checkout init --no-cone
cat > .git/info/sparse-checkout <<'EOF'
/*
!/dobtor_doc_editor/tests/
!/dobtor_doc_import/tests/
EOF
git checkout dev-18.0
```

**git 2.19（舊機制，2026-10-10 在這台 host 實測可用）**

```bash
git clone --no-checkout <repo> addons
cd addons
git config core.sparseCheckout true
cat > .git/info/sparse-checkout <<'EOF'
/*
!dobtor_doc_editor/tests/
!dobtor_doc_import/tests/
EOF
git read-tree -mu HEAD
```

☠️ `!` 樣式一定要**含模組名**：寫 `!tests/` 會踩陷阱一。
兩種寫法 2026-10-10 都在這台 host 上實測過（本機 clone ＋ `git read-tree -mu HEAD`）：

| `.git/info/sparse-checkout` 的第二行 | `*/tests/` | `static/tests/` | 兩模組合計 |
|---|---|---|---|
| `!dobtor_doc_editor/tests/` ＋ `!dobtor_doc_import/tests/` | 排掉 | **留著** | 9.0 MB |
| `!tests/` | 排掉 | **也被排掉** ✗ | — |

設好之後**一定要看一眼**：

```bash
ls dobtor_doc_editor/static/tests/tours/   # 要看到 doc_editor_panels_tour.js
```

## 4. 不要做的事

- **不要把排除規則放進這個 repo。** `.gitattributes` 的 `export-ignore` 對
  `clone`／`pull` 無效（只對 `git archive`），放進去只會得到一條看起來有效、
  實際上什麼都沒做的規則——本模組踩過好幾次這個形狀。
- **不要只排掉一邊的 `tests/`。**
  `dobtor_doc_import/tests/test_import_routes.py` 與 `test_font_serve.py`
  會 `from odoo.addons.dobtor_doc_editor.tests.session_probe import …`
  ——核心的 `tests/` 是跨模組公開介面。要排就兩個一起排（正式機兩個都不跑測試，
  沒問題），但**不要**在還要跑測試的機器上只排核心那一邊。
- **不要刪 `tests/fixtures/` 裡的檔案來省空間。** 那 82 MB 已經量過：
  全部被 `readdirSync` 列舉，290 支 LibreOffice 上游語料庫全被測到，
  不是冗餘（見 [`OPTIMIZATION_RECOMMENDATIONS.md`](OPTIMIZATION_RECOMMENDATIONS.md)）。
  要省的是**正式機的硬碟**，不是 repo 的內容。
