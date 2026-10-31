# search 実装の議論メモ（2026-10-20〜）

`search` と `search_dataset` の実装に関する議論を、ユーザーの質問ごとにまとめたもの。
用途：翌日以降の見返し、取りこぼし防止、README.md（Retrieval method / Design decisions / Challenges）作成の材料。
index の議論は `INDEX_DISCUSSION.md` を参照（Q番号は search 側で1から振り直す。index 側を指すときは「index Q45」のように書く）。

ライブラリの挙動は、インストール済みのソース（bm25s 0.3.14、pydantic 2.13.5）で確認したものだけを書く。

---

## 0. 現在の状態

### 課題の要件（subject v2.0 の VI.2、VII.1）

- 質問に対して、関連の強い上位 k 件のソースを返す。ソースは `file_path` と文字の範囲（`first_character_index`、`last_character_index`）で、**幅は2000文字以下**
- `file_path` は `data/raw/vllm-0.10.1/...` の形で**文字列として完全一致**しなければならない
- **1問だけ**（`search`）と、**データセット全体**（`search_dataset`）の両方で動くこと
    - `search <query> --k <int>`：上位 k 件のソースを返す（"ranked source locations, each with its file path and character span"）
    - `search_dataset --dataset_path <path> --k <int> --save_directory <dir>`：`StudentSearchResults` の JSON ファイルを書き出す
- recall@5：**docs 80% 以上、code 50% 以上**。正解は「同じファイル」かつ「IoU 0.05 以上の重なり」
- 速度：**200問で90秒以内**
- 使うモデル（VI.4）：`RagDataset`（入力）、`MinimalSource`、`MinimalSearchResults`、`StudentSearchResults`（出力）。項目の追加は許されている

### index から引き継いだもの

- 入力：`<processed_dir>/chunks.json`（`Chunk` のリスト）と `<processed_dir>/bm25/`（bm25s の索引）。**`chunks.json` の i 番目 = 索引の i 番目の文書**（index Q45）
- クエリは索引と**同じ `tokenize`** で区切る（index Q40）
- 想定している流れ：`bm25s.BM25.load` と `chunks.json` を読む → クエリを `tokenize` → 上位 k 件の番号とスコア → 番号で `Chunk` を引き、`text` を除いて `MinimalSource` に詰め替える（index Q45）
- 既知の問題（index の「0」より）：
    - 未知の単語だけのクエリでも、bm25s は点数0のチャンクを k 件返す（index Q39）
    - `question_id` は入力からそのままコピーする。新しい UUID を振ると recall が0になる（CLAUDE.md）
    - `RagDataset` の `List[AnsweredQuestion | UnansweredQuestion]` で `sources` が落ちる可能性（evaluate で確認する）
    - moulinette が余分な項目を許すかは未確認
    - Fire は型ヒントで変換しない。クエリが数字だけだと int で渡る（CLAUDE.md）

### 実装済み（search コマンドとコアのロジック、2026-10-20、コミットはまだ）

| ファイル | 中身 |
|---|---|
| `src/search.py`（新規） | `Retriever` クラス。`__init__(processed_dir)` で `chunks.json`（`TypeAdapter(list[MinimalSource]).validate_json`）と `bm25/`（`bm25s.BM25.load`）を1回だけ読む。`search(query, k)` は `tokenize` → `retrieve(..., show_progress=False)` → 番号で `MinimalSource` を引いて返す（Q6 で `Chunk` を廃止） |
| `src/chunker.py`、`src/index.py`、`src/data_models.py` | Q6：`chunks.json` を本文なしにし、`Chunk` クラスを削除 |
| `src/__main__.py` | `search(query, k, processed_dir="data/processed")`。1行に1件、`<file_path> [<first>:<last>]` の形で k 行出す。数字だけのクエリは `str()` で文字列に戻す |

| `src/search.py` | 関数 `search_dataset(dataset_path, k, save_directory, processed_dir)`。`RagDataset.model_validate_json` で読み、`Retriever` を1回だけ作って全問を検索。`question_id` と `question` は入力からコピー。`StudentSearchResults` を `save_directory/<入力と同じファイル名>` に書き、そのパスを返す（課題 VI.7.2 の例：`--save_directory data/output/search_results/UnansweredQuestions` → `.../dataset_docs_public.json`） |
| `src/__main__.py` | `search_dataset(dataset_path, k, save_directory, processed_dir="data/processed")`。`Saved student_search_results to <path>` と出す（課題の例と同じ文言） |

- 実測（公開データ、`--k 10`）：docs 100問で約0.7秒、code 99問で約0.4秒（コマンド全体）。`question_id` はすべて入力と一致。範囲の幅の最大は1999文字
- 実測：「How do I set the max model length?」`--k 3` → 上位3件は index Q39 と同じファイル。コマンド全体で約0.4秒
- `search 123 --k 1` は動く。未知の単語だけ（`zzqqxx`）でも、点数0のチャンクが k 件返る
- flake8 通過。mypy のエラーは、中身が空の残りのコマンド4件だけ

### 決めたこと（実装時の仮決定。ユーザーの確認待ち）

- `search` の出力は **1行に1件、`<file_path> [<first>:<last>]` を k 行**（2026-10-20 ユーザーの指示で決定。最初は `MinimalSearchResults` の JSON にしたが、見やすさのため変更。UUID も不要になった）
- `processed_dir` を引数で受け取る（既定値 `data/processed`。パスをハードコードしない要件のため）
- 番号 → `MinimalSource` の変換は自分で行う。`retrieve` の `corpus` 引数にチャンクを渡す方法もあるが、番号を受け取るほうが単純
- `bm25s` の `retrieve` は `List[List[str]]`（クエリのトークンのリストのリスト）を受け取る。`return_as="tuple"`（既定）で `(番号, 点数)` を返し、どちらも形は `(クエリ数, k)`

### 未決事項

- 点数0の結果の扱い（今はそのまま返す）
- エラー処理：`k` が0以下、`k` がチャンク数より大きい（bm25s が `ValueError`）、`--k abc`、データセットのファイルがない・壊れた JSON、保存先が作れない
- **索引（`build_index` の作成物）が見つからないときのエラー処理がない**（2026-10-21 ユーザーの指摘）。`Retriever.__init__` で起こりうるもの：
    - `chunks.json` がない → `FileNotFoundError`（確認済み：`--processed_dir /nonexistent`）
    - `chunks.json` はあるが `bm25/` がない → bm25s の `load` で `FileNotFoundError`（未確認）
    - `chunks.json` が壊れている、形式が古い → pydantic の `ValidationError`
    - 案：`Orchestrator` で捕まえ、「先に `index` を実行してください」と出して終了する
    - **決定（2026-10-21）：エラー処理の段階で、全コマンドとまとめて実装する**

---

## 1. 質問ごとのまとめ

### Q1. search コマンドは何を返すのか

- 質問文に対して、関連の強い上位 k 件を返す。ただし返すのは**ファイルではなくチャンク**（課題の "source location"：ファイルパス＋文字の範囲）
- 同じファイルの別の場所が複数の結果になることがある。k 件 = k 個の別々のファイルとは限らない
- 結果は点数の高い順（"ranked"）
- 採点はファイルが合うだけでは足りず、範囲が正解と IoU 0.05 以上重なる必要がある

### Q2. search の中で IoU（正解との重なり）を確認してよいか

- **してはいけない**（ユーザーと意見が一致）
    1. search が受け取るのは質問文だけ。`search_dataset` の入力も課題の手順では `UnansweredQuestions`（`sources` なし）。正解がないので計算できない
    2. `AnsweredQuestions` を読んで正解に寄せるのは、答えを見ながら解くのと同じ。審査用のデータは別物の可能性があり、通用しない。課題 PDF に明記された禁止文は見つからなかったが、システムの目的から考えてルール違反
    3. IoU を使うのは検索が終わった後の採点だけ：`evaluate`（"for your own testing"）と moulinette
- 正当な工夫は「正解に重なりやすいチャンクを作っておく」こと（大きさ、overlap、区切り方）。evaluate の結果を見てそれらを調整するのは問題ない

### Q3. search の大まかな流れと、使うデータモデル

- ユーザーのイメージ：search 実行 → `chunks.json` から質問に合うチャンクを k 個選ぶ → `file_path` と範囲を出力し、課題の形式の JSON を作る（`StudentSearchResults`）
- 修正1：**選ぶのは `bm25/` の索引**。`chunks.json` に点数はない
    ```
    質問文 → tokenize → bm25/ で点数を計算し、上位 k 件の「番号」を得る
                      → 番号で chunks.json を引き、file_path と範囲を得る
    ```
- 修正2：**JSON ファイルを作るのは `search_dataset` だけ**
    - `search <query> --k`："Return the top-k sources for a single query."。画面に出すだけ（`--save_directory` もない）
    - `search_dataset`："write a StudentSearchResults JSON file"

| コマンド | 使うモデル |
|---|---|
| `search` | `MinimalSearchResults`（1問分）。`question_id` は UUID を自動で振る |
| `search_dataset` | `StudentSearchResults`（`MinimalSearchResults` のリスト＋`k`）。`question_id` は入力からコピー |

- `search` の画面の出し方（JSON か、見やすい表か）は課題で指定がない → 未決事項

### Q5. 課題が指定するデータモデルと、今のコードは合っているか

- 指定は VI.5 Output："Each command writes a JSON file … For search operations: Use StudentSearchResults model"。VI.6 にも `search_dataset` は "write a StudentSearchResults JSON file"
- `search_dataset`：満たしている
- `search`（1問）：グレー。VI.6 にはモデルも保存先もない。"Each command" を文字どおり読むと含まれる可能性がある
- ユーザーの考え：1問分なので `MinimalSearchResults` を作るのが自然。VI.5 に忠実にするなら1件の `StudentSearchResults`。どちらでも説明はつく → **未決**（表示を行の形のままにするかも含めて）

### Q6. search で Chunk を経由する必要はあるか → chunks.json から本文を外す

- search が使うのは位置だけ。pydantic は既定で知らない項目を無視する（`extra` の既定は `"ignore"`）ので、`chunks.json` を `list[MinimalSource]` として読めば `text` は捨てられる（確認済み）
- そもそも `chunks.json` は必要か：**番号 → 位置の対応表は必要**。BM25 の索引は番号しか返さず、対応はチャンク分割の結果からしか作れない。**本文は不要**：位置があれば `data/raw/` から `text[first:last]` で取り出せる。`answer_dataset` は入力が位置だけなので、「位置から本文を読む」処理はどのみち必要
- 別案：bm25s の `save(corpus=[位置の dict, ...])` → `load(load_corpus=True)` で、`retrieve` が番号の代わりに位置の dict を返す（0.3.14 のソースと小さな索引で確認。`corpus.jsonl` と `corpus.mmindex.json` が作られる。`load_corpus` の既定は `False`）
    - pydantic の検証：**作るときは不要**（自分のコードが作ったデータ）、**読むときは必要**（ディスク上のファイルは信頼の境界。V.4 "the structures you exchange between stages" も pydantic を求める）。bm25s は dict のまま返すので、`MinimalSource.model_validate` が要る
- **決定（2026-10-21）**：別案は採らず、`chunks.json` を**本文なしの `MinimalSource` のリスト**にする。`build_index` で破綻なく作れているため。**`Chunk` クラスは削除**
- 実装：
    - `chunk_text` は `list[tuple[MinimalSource, str]]`（位置と本文の組）を返す
    - `build_index` は本文をその場で `tokenize` し、位置だけを `chunks.json` に保存する。進捗バーは「Indexing」1本にまとめた
    - `Retriever` は `chunks.json` を `list[MinimalSource]` として読み、番号でそのまま返す（詰め替えが不要に）
- 結果：`chunks.json` が 22MB → 約2MB。検索結果は変更前と同じ。14,638チャンクから50件ごとに抜き出した293件で、`data/raw` から読み直した本文が空でなく2000文字以下であることを確認
- 注意：本文を読み直すときは index と同じ読み方（`encoding="utf-8"`）をしないと位置がずれる。CRLF の問題（index の既知の問題）も関わる

### Q7. Retriever で TypeAdapter が確かめていること（search の読解）

- `TypeAdapter(list[MinimalSource]).validate_json(...)` は、①JSON の読み込み（バイト列 → `MinimalSource` のリスト）と、②形の検証（リストか、3つの項目がそろっていて型が合うか）を1行でやる
- 確かめられないこと：中身の正しさ（`first < last`、幅、ファイルの実在）、件数が `bm25/` の文書数と一致するか（同じ `index` の実行で作られたか）。余分な項目は無視されるので、`text` 入りの古い `chunks.json` も読めてしまう
- **決定（2026-10-21）：厳密な検証は足さない**（ユーザーの判断）。両方とも `index` が1回の実行で作るので、おかしければ `index` をやり直せばよい
- 注意：落ちずに静かに間違える場合（`chunks.json` だけ古い）は気づきにくいが、普通の使い方では起こりにくい
- エラー処理の段階で：`ValidationError`、件数不足の `IndexError` を捕まえ、「`index` をやり直してください」と出す

### Q8. Retriever クラスをやめ、1問を検索する関数にする（設計の変更）

- ユーザーの判断（2026-10-21）：**コマンドごとに統制クラスを立てる方針はやめる**。`__main__.py` の各コマンドがごちゃごちゃになるため。データのやりとりはデータモデルが担うので、状態を持つクラスは不要。特に `search` コマンドの中で `Retriever` を立ち上げる形に納得がいかない
- 新しい形（ユーザーが下書き、Claude が仕上げ）：
    - `search(question: UnansweredQuestion, k, processed_dir) -> MinimalSearchResults`：1問を検索する共有の関数。呼ぶたびに `chunks.json` と `bm25/` を読み込む
    - `search_dataset(dataset_path, k, save_directory, processed_dir) -> Path`：`RagDataset` を読み、全問に `search` を呼び、`StudentSearchResults` を**この関数の中で**ファイルに書いてパスを返す（ユーザーの決定）
    - `Orchestrator.search`：`UnansweredQuestion(question=str(query))` を作って `search` に渡し、`.retrieved_sources` を1行ずつ出す
- 下書きの問題点と対応：
    - `question_id=str(ids)`：`ids` はチャンクの番号で、質問の ID ではない。ID は呼び出し元で決まり方が違う（`search` は UUID、`search_dataset` は入力からコピー）→ **引数を `UnansweredQuestion` にする**（理由はこの後ユーザーが質問する予定）
    - `MinimalSearchResults` を返すようになったので、`Orchestrator.search` は `.retrieved_sources` を回す
- 呼ぶたびに索引を読み込むコスト：1回あたり約17ミリ秒（10回の平均）。200問で約3.5秒なので、90秒の制限には問題ないと判断し、そのままにした
- 実測：`search_dataset` はコマンド全体で docs 約2.5秒、code 約2.2秒（Retriever のときは 0.7秒、0.4秒）。出力の JSON は変更前と**完全に同じ**（`cmp` で確認）
- 下書きの日本語の文字列（モジュールの途中）は残してある。最後に消す
- CLAUDE.md の「コマンドごとに統制クラスを用意し…」の方針は、この決定で古くなった（書き換え済み）

### Q9. retrieve は本当に上位 k 件を選んでいるか、`sorted` とは

- 上位 k 件の選択は bm25s の `retrieve` の中で行われる（`k=k`）。全チャンクの点数を `get_scores` で直接計算して並べ替えた上位5件と、3つのクエリで番号・点数・順番が完全に一致した
- `sorted`（既定 `True`、`bm25s/selection.py` の `_topk_numpy`）：
    - まず `np.argpartition` で上位 k 件を**集める**。速いが、k 件の中の順番はばらばら
    - `sorted=True` のときだけ、その k 件を `np.argsort` で**点数の高い順に並べ直す**
    - つまり `sorted` は「どの k 件を選ぶか」には影響せず、「k 件の並び順」だけを決める
- 決定（2026-10-21）：既定値と同じだが、点数の高い順に並べる意図を示すため **`sorted=True` を明示する**（最初は「明示しない」としたが、ユーザーが変更）。点数そのものは出力しない
- 並び順が大事な理由：recall@1、@3、@5 は先頭から数えるので、順番がばらばらだと上位の recall が下がる。`search` の出力も「点数の高い順」が前提

### Q11. データセットの置き場所

- 今は `datasets_public/public/{AnsweredQuestions,UnansweredQuestions}/` にある。課題の構成は `data/datasets/...`
- 決定（2026-10-21）：**今は移さない**。実行時に `--dataset_path` でパスを指定するので、動作に支障はない。`datasets_public/` はコミットに含めない

### Q10. docstring の見直し

- `search.py` の下書きのメモ（モジュールの途中の日本語の文字列）を削除
- `search` と `search_dataset` の docstring を PEP 257 の形（要約1行＋空行＋説明）に書き直した

### Q4. search と search_dataset の違い

- 核となる検索の処理は同じ。違うのは入力と出力。`search_dataset` は dataset を「作る」のではなく「読む」側

| | `search` | `search_dataset` |
|---|---|---|
| 入力 | コマンドラインの質問文1つ | 質問の JSON ファイル（`RagDataset`） |
| `question_id` | UUID を自動で振る | 入力からコピー（変えると recall が0） |
| 検索 | 1回 | 質問の数だけ（公開データで約100問） |
| 出力 | 画面 | `StudentSearchResults`（結果のリスト＋`k`）を JSON ファイルに |
| 注意 | クエリが数字だけだと int で渡る（Fire） | 索引は1回だけ読み込む（200問で90秒以内）。ファイルがない、壊れた JSON、保存先が作れない場合のエラー処理 |

- 作りの案：
    ```
    1問を検索する関数（索引を受け取り、質問文と k から MinimalSource のリストを返す）
      ├─ search         ：索引を読む → 1回呼ぶ → 画面に出す
      └─ search_dataset ：索引を読む → JSON を読む → 全問で呼ぶ → ファイルに書く
    ```

---

## 2. 答え合わせしていない確認の質問

（ここから追記）

## 3. 次にやること

- search の方針を決める（「0. 未決事項」）
- 1問を検索するコアの部分 → `search` → `search_dataset`
- その後 evaluate を作り、`INDEX_DISCUSSION.md` の「evaluate を実装した後にまとめてやること」に戻る

## 4. README に使えるポイント

（ここから追記）
