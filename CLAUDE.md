# CLAUDE.md — RAG 課題（42）引き継ぎメモ

vLLM 0.10.1 のリポジトリを対象にした RAG システムの課題。要件の全文は `subject.RAG_against_the_machine.en.pdf`（v2.0、英語の原文）を参照。翻訳を挟まないため、これを正とする。
このファイルは、これまでの議論で決まったこと・分かったこと・未決事項をまとめたもの。
`index` 実装以降の議論（質問ごと、未回答の確認の質問、次にやること）は `INDEX_DISCUSSION.md` にある。`search` の議論は `SEARCH_DISCUSSION.md`、`evaluate` の議論は `EVALUATE_DISCUSSION.md`、`answer` の議論は `ANSWER_DISCUSSION.md`、エラー処理の議論は `ERROR_DISCUSSION.md` にある。

## 進め方のルール（最重要）

- **一つずつ進める。先走らない。** 次に何をするかはユーザーが決める。提案はしてよいが、合意なしに次のステップへ進まない。
- **頼まれていない実装をしない。** 大きなコードを書く前に方針を確認する。
- **実装はシンプルに。**
- **ライブラリを優先し、フルスクラッチで書かない。** 使うライブラリは挙動（既定値、癖、位置の扱い）を把握し、審査で説明できる状態にする。
- **ライブラリの情報は学習済みの知識で断定しない。** 公式ドキュメントやインストールしたパッケージのソースで確かめる。
- **コアのロジックから作り、付属の機能（パス処理やエラー処理など）は後から足す。**
- docstring は PEP 257 に沿うものとする。
- 回答は日本語。README と docstring は要件により英語。

## 守らないと即アウトになる制約

- 検索結果のソースは **2000文字以下**。1件でも超えると出力全体が無効
- `file_path` は **`data/raw/vllm-0.10.1/...` の形で完全一致**（文字列として比較される）
- recall@5：**docs 80% 以上、code 50% 以上**
- インデックス作成は **5分以内**、検索は **200問で90秒以内**
- CLI は空のクエリ、k=0、存在しないファイル、壊れた JSON でも **トレースバックを出さない**
- uv（評価側は `uv sync` のみ実行）、Python Fire、tqdm、pydantic、flake8、mypy を使う
- 入出力パスは CLI 引数で設定可能にし、ハードコードしない
- moulinette を import したり呼び出したりしない
- 正解の判定は「同じファイル」かつ「IoU 0.05 以上の重なり」

## 用語（2026-10-25 ユーザーと決定。説明とメモはこれにそろえる）

| 用語 | 指すもの |
|---|---|
| **ラン**（run） | データセット全体の検索結果（`search_dataset` の出力、`StudentSearchResults`）。情報検索の評価での標準的な言葉 |
| **ヒット**（hit） | 検索結果の1件（`retrieved_sources` の要素） |
| **グラウンドトゥルース**（ground truth） | 答え合わせのデータセット全体（`AnsweredQuestions` のファイル） |
| **ゴールドソース**（gold source） | グラウンドトゥルースの中の、質問ごとの正しいソース1件（`sources` の要素） |
| **コンテキスト**（context） | Qwen に渡すときのヒットの本文 |

- 「正解」は Qwen の答えやデータセットの `answer` と紛れるので使わない
- 「ヒット率」（hit rate@k）は recall@k とは別の指標。ゴールドソースが1つの公開データでは同じ値になるが、言い分ける

## 全体の進捗（2026-10-24 時点）

| パート | 状態 | 議論メモ |
|---|---|---|
| データモデル（`data_models.py`） | 済み。課題の8モデルのみ（`Chunk` は削除） | — |
| index（`index.py`（chunker を統合）、`tokenizer.py`） | 済み。調整は evaluate の後に戻る | `INDEX_DISCUSSION.md` |
| search / search_dataset（`search.py`） | 済み。小さな未決事項あり | `SEARCH_DISCUSSION.md` |
| evaluate（`evaluate.py`） | 済み（2026-10-23 に一旦終了） | `EVALUATE_DISCUSSION.md` |
| answer / answer_dataset | **着手**（2026-10-24〜）。transformers と PyTorch を使う | `ANSWER_DISCUSSION.md` |
| index の調整（overlap、トークン化、BM25 のパラメータ、隠しディレクトリ） | 未着手。evaluate ができたので着手できる | `INDEX_DISCUSSION.md` の「3」 |
| search の未決事項（点数0の結果、`search` の出力の解釈） | 未決 | `SEARCH_DISCUSSION.md` |
| エラー処理（全コマンドまとめて） | **済み（2026-10-28）**。下の「エラー処理の方針」を参照 | `ERROR_DISCUSSION.md` |
| moulinette との比較 | 後回し（Mac では動かない。校舎の Linux で） | `EVALUATE_DISCUSSION.md` |
| **審査の Linux マシンのデバイスの確認と、torch の指定の判断** | 後回し（校舎の Linux で）。NVIDIA の GPU があるかを確かめ、今の「Linux は CPU 専用の torch」（`pyproject.toml` の `[tool.uv.sources]`）のままでよいかを決める。あわせて `uv sync` と answer が Linux で動くかも確かめる | `ANSWER_DISCUSSION.md` |
| README | 未着手。各メモの「README に使えるポイント」が材料 | 各メモ |
| Makefile | 済み（2026-10-28）。install、run、debug、clean、lint が動くことを確認。`mypy .` が `data/raw/` の vLLM まで調べて止まっていたので、`pyproject.toml` の `[tool.mypy] exclude = ["^data/"]` で除外（課題のコマンドは変えない）。`.PHONY` から未定義の `test` を削除。lint-strict（任意）も 2026-10-31 に通るようにした（tqdm は dev グループに `types-tqdm` を追加、型情報のない bm25s と fire は `[[tool.mypy.overrides]]` の `ignore_missing_imports` で名指しして除外） | — |

- 公開データでの recall@5（自作の evaluate）：**docs 0.870、code 0.677**（基準：docs 80%、code 50%）
- index：1969ファイル、14638チャンク、約2秒。`search_dataset`：100問で約2.5秒

## エラー処理の方針（2026-10-28 実装）

- **最後の砦**：`__main__.main()` で `fire.Fire` を囲み、`KeyboardInterrupt` → 終了コード130、pydantic の `ValidationError` → `Error: invalid <モデル名> data at <場所>: <要点>`、それ以外の `Exception` → `Error: <メッセージ>`、いずれも標準エラー出力に1行で、終了コード1（2026-10-30 に一度外したが、2026-10-31 に「一旦完成させる」ため戻した。ユーザーの決定）。`FireExit`（`--help` や使い方の誤り）は `SystemExit` の仲間なので捕まえない（Fire が使い方を出して終了コード2）
- **CLI の入口での確認**（`__main__.py`）：`positive_int`（`--k`、`--max_chunk_size`。bool は弾く。`--max_chunk_size` は2000まで）、`question_of`（空・空白だけのクエリはエラー。数字だけのクエリは文字列にする）。`--k 0` は search、search_dataset、answer のすべてでエラーメッセージ（ユーザーの決定。課題 VI.6 "The CLI is tested with such edge cases"）
- **index**：`raw_dir` がない・ディレクトリでない・対象ファイルが0件 → エラー（何も保存しない）。1ファイルが読めない（`UnicodeDecodeError`、`OSError`）→ 警告を出して飛ばす。読めたチャンクが0件 → エラー。`file_path` は `os.path.relpath` で作業ディレクトリからの相対パスにする（絶対パスの `raw_dir` でも `data/raw/...`。chunks.json は変更前とバイト単位で同じことを確認）
- **chunker（`index.py` 内）**：overlap は `min(200, max_chunk_size // 2)`（小さいチャンクでも動く。既定の2000では200のまま）。langchain の位置が本文と合わないチャンクは飛ばす（vLLM では0件）
- **search**：`chunks.json` がなければ「no index under ...; run the index command first」。`k` がチャンク数より大きければ切り詰める
- **CRLF**：今のまま（index も answer も `read_text` で改行を `\n` に直すので、自分の中ではそろう）。CRLF のファイルは4つ（例：`tests/test_seed_behavior.py`）、公開のグラウンドトゥルースには出てこない（ユーザーの決定）
- 確かめた結果：最初に試した16個のトレースバックが、すべて1行のメッセージになった。recall は変わらず（docs @5 0.870）
- 試していないもの：Ctrl+C、モデルのダウンロードの失敗（ネットがない）、`bm25/` だけが欠けた索引、`chunks.json` が壊れた索引（いずれも最後の砦で1行のメッセージになるはず）

## 現在のリポジトリの状態

- ルート：`src/`、`Makefile`、`pyproject.toml`、`README.md`、`uv.lock`、`.flake8`、議論メモ（`*_DISCUSSION.md`）
- `src/__main__.py`：Fire の `Orchestrator` クラス。`index`、`search`、`search_dataset`、`evaluate` は実装済み。`answer`、`answer_dataset` の中身は空
    - `fire.Fire` を囲む try/except は外す方針（Fire は `--help` 表示後も `FireExit` を投げるため）
- `make clean` は全ての `__pycache__`、`.mypy_cache`、`.pytest_cache`、`data/processed`、`data/output` を消す
- 作業ツリーにあるが git の管理外：`data/raw/vllm-0.10.1/`（展開済み）、`datasets_public/public/`（公開データセット。`data/datasets/` には移していない）、`moulinette-ubuntu`/`-fedora`、`tests/`（ローカル専用）

## 設計の方針

- コマンドごとの処理は関数として用意し、`Orchestrator` から呼び出す。データのやりとりはデータモデルに任せ、状態を持つ統制クラスは作らない（2026-10-21 変更。`SEARCH_DISCUSSION.md` Q8）
- 役割ごとにファイルを分ける
- パッケージ内の import は **相対インポート**（`from .models import ...`）に統一する。`src` 自体がパッケージ名になる（`python -m src` で起動する）ため。起動は必ず `python -m src ...`

## データの流れと各モデルの用途

```
data/raw/vllm-0.10.1/** --index--> data/processed/ (チャンク + 索引)
UnansweredQuestions/*.json (RagDataset) --search_dataset--> StudentSearchResults
StudentSearchResults --moulinette / evaluate (+ AnsweredQuestions)--> recall@k
StudentSearchResults --answer_dataset--> StudentSearchResultsAndAnswer（人間のレビュアーが読む）
```

- **`question_id` は入力からそのまま出力にコピーする。** moulinette が正解との対応づけに使っていると考えられる。新しい UUID を振ると recall が 0 になる。UUID の自動生成が役立つのは単一クエリの `search` と `answer` だけ
- `answer_dataset` の入力は位置（`MinimalSource`）だけで本文を持たない。ファイルから切り出し直すか、インデックスから引く必要がある
- `RagDataset` の `List[AnsweredQuestion | UnansweredQuestion]` は、pydantic の解釈次第で `sources` が落ちる可能性がある。`evaluate` を作るときに確認する

## 正解データの分析で分かったこと

- docs（100ソース）：`.md` が97件、`CMakeLists.txt` が3件
    - `.md` は `docs/` 以下だけでなく、リポジトリ直下の `RELEASE.md`、`SECURITY.md` も含む。`*.inc.md` もある
- code（99問）：すべて `.py`
- → **インデックスの対象は `.py`、`.md`、`.txt`（リポジトリ全体）**。`CMakeLists.txt` を名指しせず、課題の「Markdown / text chunking」に合わせて `.txt` 全体を対象にした（28ファイル、95チャンク。`benchmarks/sonnet.txt` などの雑音も入るので、recall で影響を確認する）
- 公開データ（`_public`）と審査用のデータは別物の可能性がある
- **未確認**：正解範囲の長さの分布、`last_character_index` が終端を含むかどうか、Answered と Unanswered の `question_id` の一致
- ユーザーの PC は容量の都合で vLLM の zip を展開できていない。配布ファイルは整合性が取れている前提で進める

## チャンク分割：langchain-text-splitters に決定

- バージョン 1.1.3（2026-10-02）、MIT、Python 3.10以上、依存は `langchain-core` のみ。追加は `uv add langchain-text-splitters`
- 比較して外した候補：Chonkie（依存が重い、未検証）、semchunk（Python と Markdown で区切り方を変えられない）、semantic-text-splitter（位置を返すかが不明で、空白を削る）

### 1.1.3 のソースで確認した挙動

- `RecursiveCharacterTextSplitter`：区切りのリストを左から試し、最初に見つかった区切りで分割。`chunk_size` 未満の断片は上限まで隣とつなげ、以上の断片は残りの区切りで再帰的に分割する。リストの最後が `""`（1文字単位）なので **上限は必ず守られる**。長さは既定で `len`（文字数）
- 注意すべき既定値：`chunk_size=4000`（2000の指定が必須）、`chunk_overlap=200`、`strip_whitespace=True`（チャンクの前後の空白を削る）、`keep_separator=True`（区切りを次の断片の先頭に残す）
- 位置：`split_text()` は文字列しか返さない。`add_start_index=True` の開始位置は `text.find(chunk, 前回の位置付近)` で検索し直しているだけ。終了位置は返さないので「開始位置＋長さ」で計算する
- Python 用の区切り：`['\nclass ', '\ndef ', '\n\tdef ', '\n\n', '\n', ' ', '']`
    - メソッドはタブのインデント前提。vLLM の4スペースのメソッドでは区切られない
    - `async def` は区切りに含まれない
    - デコレータが前のチャンクの末尾に残る
- Markdown 用の区切り：`['\n#{1,6} ', '```\n', 水平線, '\n\n', '\n', ' ', '']`。`from_language()` は `is_separator_regex=True` にする
- 言語指定なし（CMakeLists.txt 用）：`['\n\n', '\n', ' ', '']`
- `MarkdownHeaderTextSplitter` は使えない（既定で見出しを削り、位置を返さない）
- 以前、vLLM 全体で試したときの結果：位置のずれ0件、2000文字超え0件、約0.4秒

## 未決事項（次に決めること）

1. `chunk_overlap` の値
2. Python 用の区切りリストを自分用に直すか（4スペースのメソッド、`async def`、デコレータ）
3. 検索用（BM25／TF-IDF）のライブラリの選定。チャンク分割と同じ手順（探す → 絞る → 実際に試す）で進める
4. トークン化の方法（識別子をそのまま残すか、`_` や大文字の境目で分割するか）
5. 内部での終端の扱い（終端を含まない形に統一し、出力時に必要なら変換する案）
6. `.github` などの隠しディレクトリを対象から除外するか

## Fire の注意点（エラー処理のときに対応）

- Fire は型ヒントで変換しない。`--max_chunk_size abc` は文字列のまま渡り、比較で TypeError になる
- クエリが数字だけ（例：`search 123`）だと int として渡される
- mypy の `--disallow-untyped-defs` を通すため、`__init__(self) -> None` のように戻り値の型も書く
