# CLAUDE.md — RAG 課題（42）引き継ぎメモ

vLLM 0.10.1 のリポジトリを対象にした RAG システムの課題。要件の全文は `subject.RAG_against_the_machine.en.pdf`（v2.0、英語の原文）を参照。翻訳を挟まないため、これを正とする。
このファイルは、これまでの議論で決まったこと・分かったこと・未決事項をまとめたもの。
`index` 実装以降の議論（質問ごと、未回答の確認の質問、次にやること）は `INDEX_DISCUSSION.md` にある。`search` の議論は `SEARCH_DISCUSSION.md`、`evaluate` の議論は `EVALUATE_DISCUSSION.md` にある。

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

## 全体の進捗（2026-10-24 時点）

| パート | 状態 | 議論メモ |
|---|---|---|
| データモデル（`data_models.py`） | 済み。課題の8モデルのみ（`Chunk` は削除） | — |
| index（`index.py`、`chunker.py`、`tokenizer.py`） | 済み。調整は evaluate の後に戻る | `INDEX_DISCUSSION.md` |
| search / search_dataset（`search.py`） | 済み。小さな未決事項あり | `SEARCH_DISCUSSION.md` |
| evaluate（`evaluate.py`） | 済み（2026-10-23 に一旦終了） | `EVALUATE_DISCUSSION.md` |
| answer / answer_dataset | **未着手**（次の候補） | — |
| index の調整（overlap、トークン化、BM25 のパラメータ、隠しディレクトリ） | 未着手。evaluate ができたので着手できる | `INDEX_DISCUSSION.md` の「3」 |
| search の未決事項（点数0の結果、`search` の出力の解釈） | 未決 | `SEARCH_DISCUSSION.md` |
| エラー処理（全コマンドまとめて） | 未着手。各メモの「既知の問題」「未決事項」に一覧 | 各メモ |
| moulinette との比較 | 後回し（Mac では動かない。校舎の Linux で） | `EVALUATE_DISCUSSION.md` |
| README | 未着手。各メモの「README に使えるポイント」が材料 | 各メモ |

- 公開データでの recall@5（自作の evaluate）：**docs 0.870、code 0.677**（基準：docs 80%、code 50%）
- index：1969ファイル、14638チャンク、約2秒。`search_dataset`：100問で約2.5秒

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
