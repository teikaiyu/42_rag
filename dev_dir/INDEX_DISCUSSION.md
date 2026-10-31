# index 実装の議論メモ（2026-10-15〜20）

`index` コマンドの実装を始めてからの議論を、ユーザーの質問ごとにまとめたもの。
用途：翌日以降の見返し、取りこぼし防止、README.md（Chunking strategy / Design decisions / Challenges）作成の材料。

ライブラリの挙動はすべて、インストール済みのソース（langchain-text-splitters 1.1.3、pydantic 2.13.5、bm25s 0.3.14）で確認したもの。

---

## 0. 現在の状態

### 実装済み（段階1：ファイル収集 → チャンク分割 → 保存）

| ファイル | 中身 |
|---|---|
| `src/index.py` | `TARGET_SUFFIXES = {".py", ".md", ".txt"}`、`collect_files()`、`build_index()` |
| `src/chunker.py` | `build_splitters()`（拡張子 → 分割器）、`chunk_text()`（Document → Chunk） |
| `src/data_models.py` | `Chunk(MinimalSource)` に `text: str` を追加 |
| `src/__main__.py` | `index(max_chunk_size=2000, raw_dir="data/raw", processed_dir="data/processed")` |
| `pyproject.toml` / `uv.lock` | `langchain-text-splitters`、`tqdm` を追加 |

- 出力：`<processed_dir>/chunks.json`（`list[Chunk]` を pydantic の `TypeAdapter` で書き出し）
- 実測：1942ファイル → 14638チャンク、約0.6秒、最大長2000、約23MB
- flake8 は通過。mypy のエラーは未実装の他の5コマンド（戻り値の型なし）だけ
- コミット済み（`fee2cfd`、`3e23081`、2026-10-16）
- **段階1は暫定的に終了（2026-10-19）。** コアロジックの `_split_text` は、全体の実装が終わったときにもう一度確認する

### 実装済み（段階2：BM25 の索引、2026-10-19。読解は 2026-10-20 に終了し、コミット済み）

| ファイル | 中身 |
|---|---|
| `src/tokenizer.py`（新規） | `tokenize(text)`：識別子を丸ごとと部品の両方で残す（Q36） |
| `src/index.py` | 定数 `CHUNKS_FILE = "chunks.json"`、`BM25_DIR = "bm25"`。`build_index` の最後で、トークン化 → `bm25s.BM25().index()` → `save(processed_dir/bm25)` |
| `tests/test_tokenizer.py`（新規） | `tokenize` のテスト3件 |
| `pyproject.toml` / `uv.lock` | `bm25s>=0.3.14`（lock は 0.3.14）、依存の numpy 2.5.4 |

- 出力：`<processed_dir>/chunks.json` と `<processed_dir>/bm25/`（`data`、`indices`、`indptr` の `.npy` が3つ、`vocab.index.json`、`params.index.json`）
- **2026-10-21 変更**：`chunks.json` は本文なしの `MinimalSource` のリストになり、`Chunk` クラスは削除した（search の議論 `SEARCH_DISCUSSION.md` Q6）。以下の記述で `Chunk` とあるのは変更前のもの
- **`chunks.json` の i 番目 = BM25 の i 番目の文書**（docstring に明記。Q26）
- 実測（作業用フォルダに展開した vLLM、1969ファイル）：14638チャンク、`index` 全体で約2.2秒、BM25 の索引 9.9MB、`chunks.json` 22MB
- `load` した索引の文書数は `chunks.json` と一致（14638）
- flake8 通過、pytest 3件通過、mypy は既存の `__main__.py` の5件だけ

### 決めたこと

- 検索ライブラリは **bm25s**。4つの候補を実測で比べて確定（Q32）。`uv add bm25s` で追加し、バージョンは `uv.lock` で固定する（Q37）
- BM25 のトークン化に LLM（Qwen）のトークナイザは使わない。正規表現で自分で書く（Q34）
- 進め方は段階的に。段階1（保存まで）→ 段階2（BM25 の索引）
- 対象ファイルは拡張子 `.py`、`.md`、`.txt`。拡張子のないファイルは除外（Q10、Q11）
- 分割器は拡張子をキーにした辞書。用意し忘れた拡張子は `KeyError` で気づける（Q16）
- **Python 用の区切りリストは調整しない（2026-10-20 決定）**。癖（4スペースのメソッド、`async def`、デコレータ）は Q18 を参照
- **1文字の語を捨てる処理（`len(t) > 1`）は残す（2026-10-20 決定）**。索引に入るトークンを減らせるため（Q46）

### 仮決定（未決事項として残っているもの）

- `last_character_index` は終端を含まない（`text[first:last]` で本文が取れる）
- `chunk_overlap` は langchain の既定の200のまま。**決定（2026-10-19）**：200のまま段階2に進み、`evaluate` ができてから 0／200／400 などを実測で比べて決める（Q31）
- 隠しディレクトリ（`.github`、`.buildkite` など）も対象に含める。ユーザーの所感は「除外してよい」。調査結果は Q47
- トークン化：識別子は丸ごとと部品の両方、小文字、1文字の語と英語のストップワード（bm25s 付属の33語）を除く、語幹化なし（Q36）。`evaluate` ができたら「丸ごとだけ」「部品だけ」「両方」を比べる
- BM25 のパラメータは bm25s の既定のまま（`method="lucene"`、`k1=1.5`、`b=0.75`）

### 既知の問題（エラー処理の段階で対応）

- `--max_chunk_size` が200未満だと ValueError（overlap 200 > chunk_size、Q4）
- `--raw_dir` に絶対パスを渡すと、`file_path` が `data/raw/...` の形にならない
- 読み込みエラーの方針は**決定済み**（Q24）。実装はまだ：
    - ファイル単位のエラー（`UnicodeDecodeError`、`PermissionError` など）→ そのファイルを飛ばして警告を出し、処理を続ける
    - 全体に関わるエラー（`raw_dir` が存在しない、ディレクトリでない、対象ファイルが0件）→ 保存せずにエラーメッセージを出して終了する。今は 0 チャンクで「成功」と出てしまう
    - CRLF：`read_text` が `\r\n` を `\n` に変換するので位置がずれる → `open(..., encoding="utf-8", newline="")` で読む
- 保存先：`processed_dir` の位置にファイルがあると `FileExistsError`、権限がないと `OSError`。`Orchestrator.index` で捕まえる
- `find` が `-1` を返した場合の防御がない（Q13）
- 検索結果を出力するときは、`Chunk` から `text` を除いて `MinimalSource` に詰め替える（moulinette が余分な項目を許すかは未確認）
- 未知の単語だけのクエリでも、bm25s は点数0のチャンクを k 件返す（search で扱いを決める。Q39）
- pytest は `uv run python -m pytest` で実行する必要がある。`uv run pytest` だと `src` を import できない。Makefile の `test` ルールは未確認
- bm25s が自前の進捗バーを4本出す（表示が騒がしい）
- bm25s には `py.typed` がない。必須の `lint`（`--ignore-missing-imports`）は通るが、`lint-strict` では import がエラーになる（Q32）

---

## 1. 質問ごとのまとめ

### Q1. index コマンドを実装したい

- 決めること：検索ライブラリ、実装の範囲
- 候補（PyPI で確認）
  - bm25s 0.3.13：依存は numpy のみ。save/load を内蔵 → **採用**
  - scikit-learn（TF-IDF）：依存が重め
  - rank-bm25：2022年で更新が止まっていて、保存機能もない → 除外
  - tantivy：Rust 製の検索エンジンで、審査で説明しにくい → 除外
- 流れ：①ファイル収集 → ②拡張子ごとに分割器を選ぶ → ③チャンク化（位置付き）→ ④保存
- 課題の「パスはハードコードしない」に合わせて、`--raw_dir` と `--processed_dir` を追加した

### Q2. 進め方

- 「一つずつ理解を深めていく。俺の理解度を軸にして」
- 一度に1つの部品だけを説明し、理解を確かめてから次へ進む

### Q3. RecursiveCharacterTextSplitter とは

- 2段構え：親の `TextSplitter`（設定値、つなげる処理、位置を付ける処理）と、子のこのクラス（どこで切るか）
- コンストラクタの引数：`separators`（既定 `["\n\n", "\n", " ", ""]`）、`keep_separator=True`（親の既定は False）、`is_separator_regex=False`、`**kwargs` は親へ渡る
- 自身が持つメソッド：`split_text`（入口）、`_split_text`（本体）、`from_language`、`get_separators_for_language`

### Q4. TextSplitter（親クラス）とは

- 抽象クラス（`ABC` と `@abstractmethod split_text`）なので、直接インスタンス化できない
- 設定値と既定値：`chunk_size=4000`、`chunk_overlap=200`、`length_function=len`、`keep_separator=False`、`add_start_index=False`、`strip_whitespace=True`
- コンストラクタで検証する：`chunk_size <= 0`、`chunk_overlap < 0`、`chunk_overlap > chunk_size` はいずれも ValueError
- 呼び出しの流れ：`create_documents` → `split_text` → `_split_text` → `_merge_splits`
- `Document` は `page_content` と `metadata`（辞書）を持つだけの入れ物

### Q5. length_function（文字数）と LLM のトークン数のギャップ

- 問題：コンテキストからあふれる、トークン数の予算が読めない（コードと文章で文字/トークンの比率が違う）、小さいモデルは長い文脈に弱い
- **索引の段階は文字数で正しい**：課題の制約（2000文字、moulinette の `max_context_length`）は文字数で決まっている。トークン数で切ると2000文字を超えるチャンクができうる
- ライブラリの対処
  - `length_function` の差し替え：`from_huggingface_tokenizer`、`from_tiktoken_encoder`
  - `TokenTextSplitter`：トークン単位で切る。区切りを考えないので今回の要件に合わない
  - 文字数とトークン数を両方守る機能はない（自前の length_function が必要）
- 方針：answer の段階で Qwen のトークナイザで数え、上限に収まるだけのチャンクを入れる

### Q6. collect_files はなぜソートするのか

- 訂正：`rglob("*")` は直下だけでなく、**再帰的に**たどる
- `rglob` の順番は OS やファイルシステムに依存する（macOS の APFS と Linux の ext4 で違いうる）
- 目的は**再現性**で、正しく動かすためではない。チャンク分割の時点では、各チャンクの中身や位置は変わらない。変わるのは `chunks.json` の並び順だけ
- BM25 を足したあと：同点の順位がチャンクの番号に依存するので、並び順が top-k に影響しうる
- 代償は無視できる程度

### Q7. チャンク分割の時点では BM25 は使われていない

- その認識で正しい。Q6 の「同点の順位」の話は段階2以降のこと

### Q8. chunks.json という名前の根拠

- 課題の指定ではない（課題は「`data/processed/` の下に保存」とだけ書いている）
- 中身が `list[Chunk]` だから複数形。pydantic で JSON に書き出すから `.json`。BM25 の索引とは別のファイルにする前提
- 課題：ファイル名がハードコードされている → `search` を作るときに定数にして共有する。bm25s の保存の仕組み次第で、構成を見直す可能性がある

### Q9. TypeAdapter の挙動

- `BaseModel` ではない型（`list[Chunk]`）にも、pydantic の検証と書き出しを使えるようにする道具
- `dump_json` は **bytes を返す**（だから `write_bytes`）。読み込みは `validate_json`、`validate_python`
- エラーの `loc` で「何番目の、どの項目が悪いか」がわかる
- 既定は lax モード：`"5"` は `5` に変換される。厳密にするなら `strict=True`
- 別案：包むモデル（`RagDataset` と同じ形）、標準の `json`（検証なし → 方針に合わない）
- `TypeAdapter` は作るのにコストがかかるので、ループ内で毎回作らない

### Q10. TARGET_FILENAMES を消して .txt を対象にすべきでは

- **採用**。課題の「Markdown / text chunking」に合わせて `.txt` を拡張子として扱う。`CMakeLists.txt` も `.txt` に含まれる
- 補足：課題は `.txt` を義務づけてはいない（「Read the files you judge useful」）。要件の言葉に合わせた選択、と説明するのが正確
- 実測：28ファイル、95チャンク
- 注意：`benchmarks/sonnet.txt`（シェイクスピア）や `tests/prompts/summary.txt` などの雑音が入る。recall で影響を確認する

### Q11. 拡張子の指定は .py だけでよいのか / 拡張子のないファイルは

- `.py` だけではだめ。`.md` は自分で指定しないと集まらない
- **「どう切るか」（分割戦略、2つの実装が必須）と「何を読むか」（自分で判断）は別の決定**
- `.c` や `.cu` を除く本当の理由は「正解データが参照していなくて、雑音になるから」。「分割戦略がないから」ではない
- 拡張子のないファイルは16件（`LICENSE` が3件、`Dockerfile`、`README`、各種 dotfile など）→ **除外（今のまま）**。suffix の許可リスト方式なので、自動的に除外される
- `Path(".gitignore").suffix` は `""`（ドットで始まる名前は拡張子として扱われない）

### Q12. _split_text と _merge_splits はライブラリ内にあり、間接的に使われているのか

- その通り。私たちのコードが直接呼ぶのは `create_documents` だけ
- `_` で始まる名前は、内部用という慣習。ただし、チャンクの切れ目、長さ、overlap は実際にはこの2つで決まる

### Q13. create_documents の挙動

- 入力はテキストのリスト。`metadatas` はテキストごとの付加情報。`deepcopy` するのは、辞書を共有すると `start_index` が上書きされるから
- `split_text` が `[]` を返すと（空のファイル）、チャンクは0個（1942ファイル中1820ファイルだけにチャンクができた理由）
- 開始位置：`offset = 前の開始位置 + 前の長さ − chunk_overlap` を下限にして `text.find(chunk, offset)` で探す
- 前提は「実際の重なりは `chunk_overlap` 以下」（Q19 で保証されている）
- 落とし穴
  1. 見つからないと `-1` が入り、エラーにならない（未対策）
  2. 同じ文字列が繰り返し出てくると、別の場所を指すことがある（中身が同じなので、ほぼ無害）
  3. `length_function` をトークン数にすると、overlap（トークン）と offset（文字）の単位が混ざる

### Q14. create_documents は何をしたいときに呼ぶのか

- テキストを切って、チャンクごとに付加情報を付けた `Document` のリストが欲しいとき
- `split_text` は `list[str]` だけを返し、位置が取れない。私たちが使う理由は `start_index` が欲しいから、の一点

### Q15. from_language の挙動

- `@classmethod` の「別の作り方」。中身は `cls(separators=get_separators_for_language(language), is_separator_regex=True, **kwargs)` だけ
- `get_separators_for_language` は if の並んだ表。28言語。表にない言語は ValueError
- `is_separator_regex=True` を強制するのは、Markdown の `'\n#{1,6} '` のような正規表現の区切りがあるから
- `separators` を kwargs で渡すと TypeError（二重指定）。区切りを自分用に直すときは、コンストラクタを直接呼ぶ

### Q16. build_splitters の "" は何を想定しているか

- 「どの拡張子にも当てはまらないもの」用の汎用の分割器だった
- 問題点：`""` は拡張子のないファイルの suffix とも同じで紛らわしい。対象の決定が2か所に分かれ、分割器を用意し忘れても気づけない
- **修正済み**：キーを `".txt"` にして、`splitters[path.suffix]` で引く

### Q17. 理解が足りていない箇所の洗い出し

- A（未読）：`_split_text`、`_merge_splits`、`chunk_text`、`build_index` の残り、Fire との連携
- B（答え合わせしていない確認の質問）→ 下の「2」を参照
- C（認識のずれ）：rglob は再帰的、分割戦略と対象ファイルは別の決定、BM25 はまだない
- D（仮決定）：終端の扱い、overlap 200、Python 用の区切りの癖

### Q18. _split_text（コアロジック）

1. **区切りを選ぶ**：リストを左から見て、**テキストに1回でも出てくる最初の区切り**を選ぶ。右側の残りは再帰用に取っておく
2. **切る**（`_split_text_with_regex`）：`keep_separator=True` なら、区切りを**次の断片の先頭**に残す → 断片を `""` でつなげば元のテキストに戻る。区切りが `""` なら1文字ずつ
3. **振り分ける**：`len < chunk_size` の断片はためる。長い断片が来たら、ためていた分を `_merge_splits` で確定し、長い断片は残りの区切りで再帰する

- 実例（`chunk_size=12`）：`"aaa bbb\n\nccc ddd eee fff ggg\n\nhh"` → `['aaa bbb', 'ccc ddd eee', 'fff ggg', 'hh']`
- 性質
  - 上限は必ず守られる（最後は `""`）。判定は「未満」
  - つなげるのは、同じ階層の隣り合う短い断片どうしだけ → 上限よりかなり短いチャンクもできる
  - 区切りは文字列が出てくるかだけで選ばれ、構文は見ない
    - 4スペースのメソッドは `'\ndef '` に当たらず、空行で切られる
    - docstring の中の行頭の `class ` でも切れる
  - デコレータは前のチャンクの末尾に残る

### Q19. _merge_splits

- 短い断片を前から箱に詰め、あふれたら確定する。確定後は**箱の先頭から捨て、残りが `chunk_overlap` 以下になったら止める** → 残りが次のチャンクに持ち越される（＝overlap）
- 実例（断片 `['aa', ' bb', ' cc', ' dd', ' ee', ' ff']`、size 9）
  - overlap 0：`['aa bb cc', 'dd ee ff']`
  - overlap 3：`['aa bb cc', 'cc dd ee', 'ee ff']`
  - overlap 6：`['aa bb cc', 'bb cc dd', 'cc dd ee', 'dd ee ff']`
- 性質
  - overlap は断片単位でしか作られない。実際の重なりは `chunk_overlap` **以下**
  - 末尾の断片が `chunk_overlap` より長いと、重なりは0（例：`['aa', ' bbbbbb', ' c']` → `['aa bbbbbb', 'c']`）。「200重なる」は上限であって保証ではない
  - 再帰の境目には overlap がない
  - これが `create_documents` の offset の下限を保証している
  - strip して空になったチャンクは捨てられる

### Q20. chunk_text

- `create_documents([text])` → `metadata["start_index"]` → `Chunk(file_path, start, start + len, text)`
- 終端が正しい理由：keep_separator で区切りが残る → `""` でつなぐ → strip は前後だけ → チャンクは元のテキストの連続した一部 → `find` の結果なら `text[start:start+len] == chunk` が必ず成り立つ
- 注意：「ずれ0件」の検証は、上の理由でほぼ必ず通るもの。本当のリスクは `-1` と、繰り返し出てくる文字列
- `Chunk` は作った時点で pydantic が検証する
- 本文を保存するのは BM25 と answer のため（約23MB）
- 出力するときは `MinimalSource` に詰め替える

### Q21. index パートのコアロジックは _split_text か

- チャンク分割に限れば、`_split_text`（どこで切るか）、`_merge_splits`（長さと overlap）、`create_documents`（位置）の3つで決まる。`_split_text` だけでは長さも位置も決まらない
- index 全体のもう一つの柱は BM25 の索引（段階2、未実装）
- 自分で書いたコードの中心は `chunk_text`（langchain の出力を、課題が求める位置の形に変換する部分）

### Q22. build_index は名前どおり索引を作っているのか

- 今は作っていない。チャンクの一覧を作って保存し、その数を返すだけ
- 段階2で、BM25 の索引を作って保存する処理を足せば、名前と中身が一致する。課題の言う index は「チャンクの一覧 + BM25 の索引」全体を指す
- **決定：`build_index` のまま**。段階2で BM25 の索引を作る処理をこの中に足すので、最終的に名前と中身が一致する

### Q23. Orchestrator.index から build_index までの流れのすり合わせ

- `raw_dir` と `processed_dir` は課題の `index` に定義されていない引数（ハードコードしないために追加した）。評価用のスクリプトは `index --max_chunk_size 2000` だけを実行するので、**既定値が課題のレイアウトと一致していることが必須**。相対パスなので、実行したディレクトリが基準になる
- `as_posix()` は Windows への保険。`data/raw/...` の形は、`raw_dir` が相対パスであることから来ている
- tqdm：ソート済みのリストを受け取るので、ファイルを集め終わってからバーが始まる。出力先は stderr。エラーが起きるのはループの本体
- KeyError：`TARGET_SUFFIXES` と分割器の対応がずれたとき（開発者のミス）だけ起きる。**`get` に戻さない**（すぐに止まるのが正しい）
- `mkdir(exist_ok=True)` が素通りするのは、既にあるのがディレクトリの場合だけ。`x.json/sub` のような拡張子っぽい名前は普通に作られる（実測）。問題になるのは、その場所にファイルがあるとき（`FileExistsError`）
- **TypeAdapter の訂正**：`dump_json` は検証しない（作った後に壊した値も、警告を出すだけで書き出された。実測）。書き出す内容の正しさは `Chunk(...)` を作った時点で保証される。書き出しだけなら `json.dumps([c.model_dump() ...])` と同じ。意味が出るのは読み込み側の `validate_json`（Q9 を補足）

### Q24. 読み込むファイルや指定のパスをいじられた場合のエラー対処

レビュー時に、コードはいじられないが、入力ファイルの中身、名前、指定のパスはいじられうる。実測の結果：

| いじり方 | 今の挙動 |
|---|---|
| 拡張子のない名前（`a`）、空のファイル、`dir.py` という名前のディレクトリ、壊れたシンボリックリンク | 除外されるか素通りする。問題なし |
| バイナリを `.py` で置く、UTF-8 でない文章（Latin-1） | `UnicodeDecodeError`（`ValueError` の一種）で全体が止まる |
| 読み取り権限のないファイル | `PermissionError`（`OSError` の一種）で止まる |
| `raw_dir` が存在しない、ファイルを指定した | エラーにならず、0チャンクで「成功」と表示する |
| CRLF のファイル | `\r` が消えて位置がずれる |

- **決定：ファイル単位のエラーは、そのファイルを飛ばして続ける**（実際の運用環境に近いため）。全体に関わるエラーは止める。詳細は「0. 既知の問題」
- `errors="replace"` で無理に読むと、文字数が変わって位置がずれるので使わない

### Q25. build_splitters と from_language、分割器を使い回すこと

- `from_language` は、言語に合わせた**ヒューリスティック**な（構文を解析しない、文字列の規則で切る）区切りを詰めた分割器を返すだけ
- **1つの分割器を、複数のファイルで使い回してよい理由：分割器は呼び出しをまたいで状態を持たない**
    - 分割器が持っているのは、`__init__` で受け取った設定（区切りのリスト、`chunk_size` など）だけ
    - `create_documents` の中の `index` や `previous_chunk_len` は、呼び出すたびに作られるローカル変数（Q13）
    - そのため、前のファイルの処理が次のファイルに影響しない
- 訂正：クラスとインスタンスの関係
    - `TextSplitter`：基本クラス（親）。`create_documents` はここで定義されたメソッド
    - `RecursiveCharacterTextSplitter`：その子クラス（基本クラスではない）
    - `splitters[".py"]` など：子クラスから作ったインスタンス。`create_documents` は分割器が「作る」ものではなく、分割器が持っているメソッド

### Q26. 位置（start_index など）は BM25 のためか

- **違う。BM25 は位置を使わない。** BM25 が使うのは本文から作った単語の情報だけ：チャンクの中での出現頻度、その単語を含むチャンクの数（レア度）、チャンクの長さ
- **位置が必要なのは、出力と採点のため**
    - `search` の出力は `file_path` + `first_character_index` + `last_character_index`（`MinimalSource`）と課題で決まっている
    - moulinette はこの範囲と正解の範囲の重なり（IoU 0.05 以上）で採点する。位置が間違っていれば、BM25 が正しいチャンクを見つけても不正解になる
    - `answer_dataset` は位置だけを受け取るので、本文をファイルから切り出し直すのにも使う
- 段階2以降の役割分担

    ```
    BM25    ：本文で順位を付ける         → 「何番目のチャンクが上位か」を返す
    chunks  ：番号 → file_path と位置    → 出力の MinimalSource になる
    ```

    2つをつなぐのはチャンクの番号（`chunks.json` の中での位置）。ソートによる再現性（Q6）が段階2で効いてくるのはこのため

### Q27. _split_text のロジック（Q18 の復習）

- 全体の関係：`split_text` → `_split_text`（切る＋振り分ける）→ `_merge_splits`（箱に詰める）
- `self._chunk_size` は、私たちの `max_chunk_size`（`build_splitters` で `chunk_size=max_chunk_size` として渡している）
- **再帰のきっかけは、断片1つが `chunk_size` 以上のときだけ。** `good_splits` にためた量が `chunk_size` を超えても再帰しない。ためた分を `chunk_size` ごとに分けるのは `_merge_splits` の役目
- 判定は「未満」でためるが、`_merge_splits` は「超えたら確定」なので、チャンクは `chunk_size` **以下**（ちょうどの長さもありうる）
- 確定の順番は**前から**（深さ優先）。長い断片に出会ったら、①それより前にためた分を確定 → ②長い断片を残りの区切りで再帰して、結果をすべて追加 → ③続きの断片へ。後ろから確定することはない
- 長い断片の中では、同じ `_split_text` を残りの区切りで最初からやり直す。実際にチャンクを確定するのはいつも `_merge_splits`
- 実行の記録（`chunk_size=12`、overlap 0、インデントは再帰の深さ）

    ```
    _split_text 'aaa bbb\n\nccc ddd eee fff ggg\n\nhh'  ['\n\n', '\n', ' ', '']
      merge ['aaa bbb'] -> ['aaa bbb']
      _split_text '\n\nccc ddd eee fff ggg'  ['\n', ' ', '']
        merge ['\n'] -> []                     ← '\n' だけの断片。strip で空になり捨てられる
        _split_text '\nccc ddd eee fff ggg'  [' ', '']
          merge ['\nccc', ' ddd', ' eee', ' fff', ' ggg'] -> ['ccc ddd eee', 'fff ggg']
      merge ['\n\nhh'] -> ['hh']
    ```

### Q28. 区切りに `\n\n` と `\n` の両方があるのはなぜか / 区切りが連続したら無視するのか

- 区切りのリストは**優先順位**。段落（`\n\n`）→ 行（`\n`）→ 単語（`" "`）→ 1文字（`""`）。`\n\n` がテキストにあればそれで切り、`\n` は長い段落を再帰で切るときだけ使う
- `\n` だけにすると、段落の境目を区別できない（`chunk_size=9`、実測）
    - 既定：`'aa\n\nb1\nb2\nb3\nb4'` → `['aa', 'b1\nb2', 'b3\nb4']`
    - `\n` だけ：→ `['aa\n\nb1\nb2', 'b3\nb4']`（段落が混ざる）
- **連続した区切りは無視しない。** `_split_text_with_regex` が捨てるのは空文字列だけ（`if s`）。区切りだけの断片として残る

    | テキスト | 区切り `\n` | 区切り `\n\n` |
    |---|---|---|
    | `a\n\nb` | `['a', '\n', '\nb']` | `['a', '\n\nb']` |
    | `a\n\n\nb` | `['a', '\n', '\n', '\nb']` | `['a', '\n\n\nb']` |
    | `a\n\n\n\nb` | `['a', '\n', '\n', '\n', '\nb']` | `['a', '\n\n', '\n\nb']` |

    - `'\n'` だけの断片を段落とみなす処理はない。ただの1文字として隣と詰められ、strip で消える
    - 正規表現は左から重ならないように一致を探すので、3つ連続なら余った `\n` が次の断片の先頭に残る
- こういう作りの理由（推測）：①区切りは文字列か正規表現で、「優先順位の高いものから試す」という1つの仕組みで段落、行、`\nclass `、Markdown の見出しを扱える。②元のテキストを1文字も失わないので、`find` で位置を探し直せる（Q13）

### Q29. _merge_splits と chunk_overlap（Q19 の復習）

- 1つずつ箱に入れていき、**次の1つを入れると `chunk_size` を超えるところで箱を閉じる**（全部まとめてから判定するのではない）。判定は「超えたら」（`>`）なので、ちょうどなら入る
- つなぐときの区切りは `""`（`keep_separator=True` だと、区切りが断片の先頭に付いたまま）
- 箱を閉じたあと：先頭から断片を捨て、合計が `chunk_overlap` 以下になったら止める（`base.py` 195〜203行）。次の断片を足すと `chunk_size` を超える場合も、さらに捨てる。残りが次のチャンクの先頭になる
- **`chunk_overlap` は上限（最大値）であって、最低値ではない。** 実際の重なりは 0 以上、`chunk_overlap` 以下。捨てるのは断片単位。再帰の境目では重ならない
- 実測（断片 `['\nccc', ' ddd', ' eee', ' fff', ' ggg']`、各4文字、`chunk_size=12`）

    | overlap | 結果 |
    |---|---|
    | 0 | `['ccc ddd eee', 'fff ggg']` |
    | 3 | `['ccc ddd eee', 'fff ggg']`（断片が4文字なので、1つも残せず重なり0） |
    | 4 | `['ccc ddd eee', 'eee fff ggg']` |
    | 8 | `['ccc ddd eee', 'ddd eee fff', 'eee fff ggg']` |

### Q30. 文の途中で切れる問題と、チャンク同士のつながり

- 単語の途中で切れるのは、1単語が `chunk_size` 以上の場合だけ。**文の途中では普通に切れる**（区切りに `" "` があり、`.` はない。Python 用、Markdown 用も同じ）
- **チャンク同士のつながりは、どこにも保存されていない。** langchain はチャンクを作るだけ。BM25 は各チャンクを独立した文書として採点する（一般論による理解。bm25s のソースは未確認）。overlap で入るのは同じ文字列のコピーだけ
- 復元する材料は持っている：`file_path` と位置が隣り合っていれば隣のチャンク。ただし、使う処理は langchain にも bm25s にも私たちのコードにもない
- 参照の解決はできない。実測（`chunk_size=25`）

    ```
    'Alex wakes up. He eats breakfast. He leaves the house.'
    overlap 0 ：['Alex wakes up. He eats', 'breakfast. He leaves the', 'house.']
    overlap 20：[..., 'breakfast. He leaves the', 'He leaves the house.']
    ```

    overlap 20 でも、`'He leaves the house.'` に `Alex` は入らない。BM25 は単語の一致で採点するので、「Alex はいつ家を出たか」というクエリでこのチャンクの点数が下がる
- **結論：overlap の役割は、意味のつながりを保つことではない。境目付近の文が、どちらかのチャンクに丸ごと入る確率を上げるだけ**（ユーザーも理解済み）
- 一般的な対策（参考、未調査）：チャンクを大きくする、回答のときに隣のチャンクも位置を使って読む、本文にファイル名や見出しを付け足して索引にする
- 今回の課題では：`chunk_size` が2000文字なので、数文の話はほとんど1つのチャンクに収まる。採点は IoU 0.05 以上なので、参照を解決できなくても致命的になりにくい

### Q31. chunk_overlap の値をどう決めるか

- 得：境目付近の文がどちらかのチャンクに丸ごと入りやすくなる
- 損：チャンクが増える（overlap 200 で14638チャンク）。中身の重なるチャンクが top-5 の枠を取り合う
- IoU 0.05 以上の採点では、overlap の得は小さめかもしれない（推測）
- 提案：200のまま段階2に進み、`evaluate` ができてから 0／200／400 などを実測で比べる。今は recall への影響を測る手段がない。変えるには `build_splitters` に `chunk_overlap` を渡すだけなので、手戻りは小さい
- **決定：この提案で進める**（2026-10-19）

### Q32. bm25s を選んだ理由（他のパッケージと比べて）

- BM25 は概念なので、パッケージは bm25s 以外にもある。実装コストと今回のプロジェクトへの合い方で選び直した
- 課題の条件（PDF の原文）：BM25 か TF-IDF を1つ実装する、ライブラリは自由（"you may use any library you like"）。索引を保存し、検索はミリ秒単位。索引の作成は5分以内、検索は200問で90秒以内。トークン化を自分で決められる必要がある（"What you keep at indexing time decides which of the two you can still match"）。mypy を通す
- 探す → 絞る：PyPI で11個を調べ、次を除外

    | 候補 | 除外の理由 |
    |---|---|
    | retriv、pyserini、bm25-pt | torch や Java など、依存が非常に重い |
    | langchain-community、llama-index-retrievers-bm25 | 中身は rank_bm25 と bm25s を包んでいるだけで、依存が重い |
    | Whoosh（2016年）、fastbm25（2022年） | 更新が止まっている |
    | Whoosh-Reloaded | 純 Python の検索エンジン一式で、大きすぎる |

- 実際に試す：実際のチャンク14638件、ランダムに作ったクエリ200問、トークン化は4つとも同じ（`\w+`、小文字化）

    | | 作成 | 読み込み | 200問 | サイズ | 依存 | 最終更新 |
    |---|---|---|---|---|---|---|
    | **bm25s** 0.3.14 | 0.47秒 | 0.01秒 | 0.02秒 | 9.1MB | numpy のみ | 2026-10-18 |
    | tantivy 0.26.2 | 0.52秒 | 0.00秒 | 0.02秒 | 2.5MB | なし（Rust 製） | 2026-09-17 |
    | rank_bm25 0.2.2 | 0.20秒 | 0.09秒 | 2.75秒 | 12.3MB | numpy のみ | 2022-02 |
    | scikit-learn（TF-IDF） | 0.36秒 | 0.01秒 | 0.13秒 | 12.8MB | scipy ほか4つ | 2026-09-10 |

    上位5件の bm25s との重なり：rank_bm25 90%、tantivy 94%、TF-IDF 52%

- **速度はどれも制限に余裕で収まるので、決め手にならない**
- bm25s を選ぶ理由：①実装コストが最も低い（`index` → `save` → `load` → `retrieve`）、②トークンのリストをそのまま渡せる、③ソースが Python で審査で説明できる（スコアの計算は `scoring.py` の432行）。`k1`、`b`、変種を引数で変えられる、④依存は numpy だけ
- tantivy（不採用）：`py.typed` があり、ファイル単位の追加と削除もできる（ボーナス3向き）。ただし中身が Rust で説明しにくい。スキーマ、writer、commit、searcher と書くコードが増える。クエリの解析器は記号で構文エラーになりうる。ボーナスは必須部分が通ってから
- rank_bm25：保存機能がなく（pickle）、検索は約100倍遅く、2022年から更新なし
- TF-IDF：課題では認められているが、BM25 と結果が半分程度しか一致しない。scikit-learn 1.9.1 は Python 3.11 以上で、プロジェクトの 3.10 以上とずれる
- 測定はランダムな単語のクエリによるもの。recall は測っていない
- 測定の過程で分かったこと：`moulinette.zip` にデータセットは入っていない。`vllm-0.10.1.zip` の `.py`、`.md`、`.txt` は1969ファイル、約20MB

### Q33. トークン化を「差し替えられる」とはどういう意味か

- BM25 の前に、文章をトークンのリストに変える処理（①トークン化）がある。BM25（②）は①が作ったトークンの一致だけで点数を付ける

    ```
    チャンクの本文 ──①トークン化──> ['def', 'get_max_model_len', ...] ──②BM25──> 索引
    クエリ         ──①トークン化──> ['max', 'model', 'len']            ──②BM25──> 順位
    ```

- bm25s は①（`bm25s.tokenize()`）と②（`BM25.index()`）を別々に提供している。`index()` は `list[list[str]]` を受け取れる（`_infer_corpus_object` で `"tokens"` と判定）ので、①は自分で書いた関数に取り替えられる
- bm25s 付属の `tokenize()` の既定：`lower=True`、`token_pattern=r"(?u)\b\w\w+\b"`（2文字以上、scikit-learn と同じ）、`stopwords="english"`、語幹化なし。`get_max_model_len` は1語のまま、`maxModelLen` は `maxmodellen`、1文字の語は捨てる
- **①は索引とクエリの両方に同じものを使う**。違うやり方で区切ると一致しなくなる
- `index()` の既定 `create_empty_token=True` で、語彙の末尾に空のトークン `''` が足される（どの単語も含まないクエリでもエラーにしないため）

### Q34. トークン化には Qwen などのモデルが必要か / vLLM の中のトークン化の関数は使えるか

- **BM25 のトークン化にモデルは要らない。** 正規表現で十分
- vLLM の中には `vllm/transformers_utils/tokenizer.py` の `get_tokenizer()`（167行）があるが、中身は HuggingFace の `AutoTokenizer.from_pretrained(...)`（239行）を包んでいるだけ
- 使えない理由：①vLLM は検索の対象（文書）であって、使うライブラリではない。import するには torch 2.7.1 などの重い依存が要る（`requirements/common.txt`、`requirements/cuda.txt`）。②そもそも別物

    | | LLM のトークン化 | BM25 のトークン化 |
    |---|---|---|
    | 目的 | モデルに文章を入力する | 単語の一致を数える |
    | 単位 | サブワード（モデルの語彙で決まる） | 単語（自分で決める） |
    | 道具 | Qwen のトークナイザ（transformers） | 正規表現 |
    | 使う場面 | answer（文脈をトークン数の上限に収める。Q5） | index と search |

- LLM のトークナイザを流用すると、単語がモデルの都合で断片化される。バイト単位の BPE では、前の空白の有無で同じ単語が別のトークンになりうる（一般論からの推測、Qwen では未確認）
- Qwen のトークナイザは answer の段階で、transformers から直接読み込む

### Q35. BM25 のトークンは何のためのものか

- 数えるための単位。数える単位は**ファイルではなくチャンク**（BM25 から見るとチャンク1つが1文書）

    | 何を数えるか | 意味 | 点数への影響 |
    |---|---|---|
    | 出現頻度（TF） | クエリのトークンが、そのチャンクの中で何回出るか | 多いほど上がる。頭打ちになる（`k1`） |
    | レア度（IDF） | そのトークンを含むチャンクが、全チャンクのうちいくつあるか | 少ないほど上がる |
    | チャンクの長さ | そのチャンクのトークン数が平均と比べて長いか | 長いほど少し下がる（`b`） |

- 例：`self` はほぼすべての Python のチャンクに出るので、ほとんど点にならない。`get_max_model_len` は珍しいので、一致すれば大きな点になる
- **区切り方がそのまま「何を同じ単語とみなすか」になる。** 1語にすれば珍しい1語として強く一致する。部品に分ければ、それぞれのレア度は下がるが、言い換えのクエリにも一致する（未決事項4のトレードオフ）

### Q36. トークン化の方針（仮決定）

- ユーザーの指示「おすすめで」を受けて決めた
- 識別子は**丸ごと**と**部品**の両方を残す。課題の "a question may paraphrase an idea or quote an identifier verbatim" に合わせ、どちらのクエリにも一致できるようにする
    1. `\w+` で単語を取り出す
    2. 小文字にして丸ごと残す
    3. `_` や大文字の境目で分けられる単語は、部品も足す（`PART = [A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+`）
    4. 1文字の語と、英語のストップワード（`bm25s.stopwords.STOPWORDS_EN`、33語）を除く
- 例

    ```
    'def get_max_model_len(self) -> int:' → ['def', 'get_max_model_len', 'get', 'max', 'model', 'len', 'self', 'int']
    'class LLMEngine: maxModelLen'        → ['class', 'llmengine', 'llm', 'engine', 'maxmodellen', 'max', 'model', 'len']
    'How do I set the max model length?'  → ['how', 'do', 'set', 'max', 'model', 'length']
    'HTTPServer v0 10 1'                  → ['httpserver', 'http', 'server', 'v0', '10']
    ```

- 入れないもの：語幹化（PyStemmer が必要。`len` と `length` は語幹化しても一致しない）、LLM のトークナイザ
- 懸念：部品を足すぶんチャンクのトークン数が増え、長さの補正が少し強くかかる。`evaluate` で確認する

### Q37. バージョンを固定する必要はあるか

- 当初の提案は `bm25s==0.3.14` での固定（0.3.14 は2026-10-18公開。読んだソースと測定が 0.3.14 だから）
- **訂正：`pyproject.toml` で固定する必要はない。** `uv add bm25s` で `pyproject.toml` には `bm25s>=0.3.14`（下限だけ）が入り、`uv.lock` に 0.3.14 が正確に記録される。`uv sync` は `--upgrade` を付けない限り `uv.lock` のバージョンを入れる（`uv sync --help` で確認）。`uv.lock` は git の管理下にある
- 既存の `langchain-text-splitters>=1.1.3` と同じ書き方にそろえた
- 注意：`uv lock --upgrade` などで上がる。上げるときはソースを確認し直す

### Q38. evaluate は search や index とは別軸で実装できるか

- **コードの上では完全に別軸。** 入力は2つの JSON（search_dataset の出力、正解の AnsweredQuestions）だけ。`question_id` で突き合わせ、同じファイルかつ IoU 0.05 以上を数えて recall@k を出す。使うのはデータモデルだけで、langchain や bm25s に依存しない。手で作った小さな JSON でテストできる
- **ただし recall の数字を出すには、index → search_dataset → evaluate がそろう必要がある**
- 注意：正解データ（`data/datasets/...`）が今の作業ツリーにない。採点の定義は `READEME_MOULINETTE.md` と照らし合わせる（本番の recall は moulinette が計算する。コードから呼ぶのは禁止だが、手で実行して答え合わせに使うのは問題ないと考えられる）。`RagDataset` で `sources` が落ちる懸念もここで確認する
- 決定：今の流れのまま、先に `build_index` に BM25 を組み込む

### Q39. build_index に BM25 を組み込む

- `save` で保存されるもの（`__init__.py` 941行〜）：スコアの疎行列（`data`、`indices`、`indptr` の `.npy`。`allow_pickle=False` が既定）、語彙（`vocab.index.json`）、パラメータ（`params.index.json`）。`corpus` は任意なので渡さない（本文は `chunks.json` にある）
- 確認したこと：トークンが0個のチャンク（ストップワードだけなど）があってもエラーにならない。未知の単語だけのクエリでも、点数0のチャンクが k 件返る
- 実装は「0. 実装済み（段階2）」を参照
- 「How do I set the max model length?」の上位3件：`docs/serving/parallelism_scaling.md`（6.8）、`docs/getting_started/installation/cpu.md`（6.06）、`vllm/v1/engine/processor.py`（6.02）。正解かどうかは未確認

### Q40. tokenize の正規表現の読み方（2026-10-20、段階2の読解）

- `tokenize(text)`：チャンク1つ分の本文（索引を作るとき）か、クエリ（search のとき）を受け取り、BM25 が数えるトークンのリストを返す。**チャンクとクエリは同じ関数で区切る**（そうしないと一致しない。確認の質問18）
- トークンは「意味の塊」ではなく**ただの文字列**。BM25 は文字列が完全に一致したときだけ点数をつける（`len` と `length` は別物）
- `re`：標準ライブラリの正規表現モジュール。`re.compile()` は、パターンの文字列（ただの文字列）を検索できる道具（`re.Pattern`）に変換する。`re` は内部で変換結果をキャッシュするので、速度の差はわずか。`compile` する主な理由は、名前をつけて先頭にまとめる読みやすさ
- `r"..."`（raw 文字列）：`\` を Python に解釈させず、そのまま `re` に渡す。`r` がないと `"\b"` がバックスペースに変わるなどの事故が起きる。`f"..."` は `{}` で値を埋め込む文字列（別物）
- `WORD = \w+`
    - `\w`：**文字クラス**（文字の集まり）。英字、数字、`_`（＋ Unicode の文字）の**どれか1文字**に一致する。`\t`（決まった1文字）とは違う
    - `+`：直前のものの1回以上の繰り返し。`\w+` で「`\w` の文字が続く塊」を取る。それ以外の文字（空白、`(`、`-`、`.`）が区切りになる
    - イメージ：**文字帳（`\w`）＋取り出し方（`+`）**。`WORD` は単語を持っておらず、ルールだけを持つ。単語は `findall` を呼んだときに初めて取り出される
    - `_` は `\w` に含まれるので、`get_max_model_len` は丸ごと1語になる
- `PART = [A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+`：3つのルールを `|`（または）でつないだもの
    - ① `[A-Z]+(?![a-z])`：略語（`LLM`、`HTTP`）。大文字の連続で、すぐ後ろに小文字が来ないもの
    - ② `[A-Z]?[a-z]+`：普通の単語（`get`、`Engine`）。先頭の大文字はあってもなくてもよい（`?` は0回か1回）
    - ③ `\d+`：数字の連続
    - `(?!...)`：否定先読み。`(` の直後の `?` は「特別なかっこ」の合図で、`(?!` の3文字で一つの記号。`!` 単独の否定ではない。文字は取らず、確認するだけ
    - `_` はどのルールの文字帳にもないので、結果的に区切りとして働く
    - 例：`LLMEngine` → `LLM`、`Engine`。`maxModelLen` → `max`、`Model`、`Len`。`10millionDollars` → `10`、`million`、`Dollars`
- `WORD` と `PART` の違い：`WORD` は文章全体に当てて丸ごとの単語を取る。`PART` は `WORD` が取った単語1つずつに当て、`_`、大文字の境目、数字の境目で分ける

### Q41. 部品を足す条件と、順番を考えない理由

- `len(parts) > 1`：部品が**2つ以上**のときだけ足す。1つのときは丸ごとと同じ文字列なので、足すと TF が倍になり、長さも水増しされる
- 丸ごとを先に `append` し、続けて部品を足す
- BM25 は **bag of words**：トークンが何回出たかだけを使い、順番は使わない（`max model len` と `len model max` は同じ点数）
- 並びが残るのは `WORD` が1つの塊として取った範囲の中だけ（`_`、大文字小文字、数字でつながったもの）。空白、`-`、`.` で区切られると並びは失われる（例：`--max-model-len` → `max`、`model`、`len`）
- `tokens` は索引そのものではなく材料。`retriever.index()` が語彙とスコアの表に作り変え、`tokens` 自体は保存されない

### Q42. vLLM のテキストに `_` でつながった語はどれだけあるか

- zip から直接数えた：`.md` は 178ファイル中154（5373回）、`.txt` は 28ファイル中10（823回）、`.py` は 1763ファイル中1635（372669回）
- `.md` で多い語：`model_executor`、`offline_inference`、`generated_text`、`getting_started`、`sampling_params`。コード例の識別子と、リンクやパスのディレクトリ名が多いと推測（内訳は未確認）
- → 丸ごと＋部品の方針は docs の質問にも効く可能性がある

### Q43. このトークン化の考え方の出どころ（レビューでのディフェンス）

- 正規表現は特定の出典を写したものではない（前回のセッションで Claude が一般的な知識から書いた）
- 同じ考え方の前例：**Lucene の `WordDelimiterGraphFilter`**（Elasticsearch では `word_delimiter_graph`）。英数字以外での区切り、`split_on_case_change`（`PowerShot` → `Power`、`Shot`）、`split_on_numerics`（`j2se` → `j`、`2`、`se`）が既定で有効。`preserve_original`（丸ごとも残す）は既定で無効 → 今回は**有効にした状態**に相当
    - 出典：https://www.elastic.co/docs/reference/text-analysis/analysis-word-delimiter-graph-tokenfilter
    - `_` を区切りにすることは、ページ上では名指しで確認できなかった。細かい挙動は Lucene と違う可能性がある
- Lucene：Apache の Java 製の全文検索ライブラリ。Elasticsearch と Solr の土台。bm25s の `method="lucene"` は Lucene の BM25 の式に合わせたもの
- Lucene の解析は「**トークナイザ → フィルタ → フィルタ …**」の流れ作業。今回の対応：トークナイザ＝`WORD`、小文字フィルタ＝`.lower()`、部品に分けるフィルタ＝`PART`、ストップワードのフィルタ＝`STOPWORDS`、短い語を捨てるフィルタ＝`len(t) > 1`
- 説明の組み立て：①課題の "paraphrase an idea or quote an identifier verbatim" に両対応するため ②Lucene の `word_delimiter_graph`（`preserve_original=true`）と同じ考え方 ③Lucene は Python から使えないので、正規表現3つで小さく再現した

### Q44. ストップワード（`STOPWORDS_EN`）

- bm25s の `bm25s/stopwords.py` にある33語：`a, an, and, are, as, at, be, but, by, for, if, in, into, is, it, no, not, of, on, or, such, that, the, their, then, there, these, they, this, to, was, will, with`
- どの文章にも多く出るので、一致しても手がかりにならない語
- bm25s のファイルに出典は書かれていないが、**Elasticsearch の既定の英語ストップワード（`_english_`）と同じ33語**（公式ドキュメントで確認。リンク先は Lucene の `EnglishAnalyzer.java`）。https://www.elastic.co/docs/reference/text-analysis/analysis-stop-tokenfilter
- より多い `STOPWORDS_EN_PLUS` もあるが、少ないほうを選んだ
- 注意：Python のキーワード（`if`、`for`、`in`、`is`、`not`）も消える。否定（`not`、`no`）は区別できなくなる

### Q45. BM25 のスコアはどこに保存され、search でどう使うか

- `chunks.json` にはチャンク（パス、位置、本文）だけ。スコアは `bm25/` にある
- スコアの表は**行＝チャンクの番号、列＝トークンの番号**（`shape=(n_docs, n_vocab)`、`__init__.py` 413行）。各マスに「そのトークンが一致したら何点か」が計算済みで入る。0以外のマスだけを CSC 形式の疎行列として `.npy` 3つに保存
- **チャンクとスコアのつながりは番号（並び順）だけ**。`chunks.json` と `bm25/` は同じ `index` の実行で作られたものでないと、番号がずれる
- `index(corpus)`（475行）：トークンのリストのリストから、語彙（トークン → 列の番号）とスコアの表を**メモリ上で**作る。既定の `create_empty_token=True` で語彙に `""` が追加される
- `save(save_dir)`（941行）：メモリ上の索引をディレクトリに書き出す（`mkdir(parents=True, exist_ok=True)`）。`params.index.json` には `k1`、`b`、`method`、`num_docs`、バージョンなど。`corpus` を渡したときだけ `corpus.jsonl` も作る
- search の流れ（予定）：`bm25s.BM25.load` と `chunks.json` を読む → クエリを同じ `tokenize` で区切る → bm25s がクエリのトークンの列を足し合わせ、上位 k 件の番号とスコアを返す（312〜318行）→ 番号で `chunks.json` を引き、`MinimalSource` にする
- **課題の要件は「`data/processed/` の下に索引を保存する」だけ**（VI.1、提出物の説明）。ファイル構成は自由。`chunks.json` と `bm25/` に分けたのは設計判断：bm25s の `save` はこちらのチャンクの情報を持てない、チャンクは pydantic で保存したい
- `bm25/` のサブディレクトリは必須ではない（`processed_dir` に直接保存してもファイル名はぶつからない）。`save` と `load` がディレクトリ単位でまとめて読み書きするので、整理のために分けた。埋め込み検索などを足したときに並べられる

### Q46. 1文字の語を捨てる処理と、トークンが0個になるチャンク

- `3importantInformation` → `['3importantinformation', 'important', 'information']`。部品の `3` は捨てられるが、丸ごとのトークンには残る
- 捨てる理由：`x`、`i`、`n` のような1文字の変数名はどこにでも出て、手がかりにならない。トークン数が増えて長さの補正にも影響する
- 失うもの：1文字の数字（`step 3` → `['step']`、`v0.10.1` → `['v0', '10']`）
- **実測（zip から直接、`max_chunk_size=2000`）**：
    - 1文字のトークンは 209,311 個で、全体の **7.3%**（残したトークンは 2,646,313）。多いのは `1`、`0`、`2`、`v`、`8`、`w`、`f`
    - 検索結果への影響は小さいと予想：どこにでも出るので IDF が低い、どのチャンクも同じように短くなる、クエリにはほぼ出ない（推測。evaluate で確かめる）
    - **トークンが0個になるチャンクは 14,638 個中6個**。すべて `.md` で、中身は `---` か `` ``` `` だけの3文字のチャンク。1文字の語を捨てる処理が原因のものは0個。原因はチャンク分割（Markdown 用の区切りに `` ```\n `` と水平線がある）で、隣とつなげられなかった理由は未調査。点数は常に0なので search に実害はない
- 決定：**残す**（索引に入るトークンを減らせるため）

### Q47. 隠しディレクトリを対象から外すか（調査のみ、未決）

- 課題の要件：**指定なし**。VI.1 は "Read the files you judge useful from the vLLM repository"（何を読むかは自分で判断する）。隠しディレクトリへの言及はない（`.gitignore` の話だけ）→ 外すなら README で理由を説明する
- ユーザーの所感：隠しディレクトリは隠したいものや形式的なデータが多く、速度や精度の質を落としそうなので、なくてもよい
- vLLM（zip）の中の隠しファイル・ディレクトリ：全134ファイル。`.buildkite`（85）、`.github`（31）、ほかは `.gitignore`、`.nav.yml`、`.meta.yml` などの設定ファイル
- そのうち対象の拡張子（`.py`、`.md`、`.txt`）は **17ファイル、39チャンク**（全14,638チャンクの約0.3%）
    - `.github/PULL_REQUEST_TEMPLATE.md`
    - `.buildkite/` の CI 用スクリプト（`check-wheel-size.py`、`generate_index.py`、`nightly-benchmarks/scripts/*.py` など）、`lm-eval-harness/` のテストと設定、`nightly-benchmarks/` の説明の `.md`
- 正解データに隠しディレクトリのファイルがあるかは**未確認**（`data/datasets/` が作業ツリーにない）。以前の分析では、docs は `docs/` 以下とリポジトリ直下の `.md`、`CMakeLists.txt`、code はすべて `.py` で、隠しディレクトリの記載はなかった

---

## 2. 答え合わせしていない確認の質問

1. 終端を含む形（`start + len - 1`）にしたら、本文を取り出すコードはどう変わるか。IoU の採点への影響は
2. `from_language` が `is_separator_regex=True` にするのはなぜか（答え：Q15）
3. トークン数（`chunk_size=500`）で切ったとき、moulinette で問題になるのはどんなチャンクか
4. Mac と Linux で `chunks.json` が変わりうる、残りの要因は（ヒント：`read_text(encoding=...)`、`file_path` の作り方）
5. `strip_whitespace=True` でも `find` で正しい位置が見つかるのはなぜか
6. `validate_json` で読み込むと、どんな事故を防げるか（ヒント：古い `chunks.json` が残っている場合）
7. `Dockerfile` だけを対象に加えるなら `collect_files` をどう変えるか。`TARGET_FILENAMES` と何が違うか
8. `offset` の式から `- chunk_overlap` を取り除いたら何が起きるか
9. `.txt` 用の分割器の `is_separator_regex` はいくつで、なぜ問題ないか（答え：`False`。`re.escape` で特殊文字を無効にしている。Q18）
10. `class ` も `def ` もない Python ファイルでは、どの区切りが選ばれるか
11. IoU 0.05 の条件のもとで、overlap を大きくすると recall の面でどんな得と損があるか
12. `build_index` で `path.as_posix()` を渡すのはなぜか
13. 断片が `['xxx', 'yyy', 'zzz']`（各3文字）、`chunk_size=5` のとき、`_split_text` は再帰を呼ぶか。呼ばないなら、どこでどう処理されるか（答え：呼ばない。どれも5未満なので `good_splits` にためられ、`_merge_splits` で詰められる。Q27）
14. Q29 の表で、断片はそのままで `chunk_size=8` にしたら、結果はどうなるか
15. Q29 の表で、overlap 8 のときにチャンクが2つから3つに増えるのはなぜか
16. `chunk_overlap=200` で、前のチャンクの末尾の断片が `[50文字, 180文字]`（右が末尾）のとき、重なりは何文字か
17. 既定の `bm25s.tokenize()`（`_` で区切らない）で索引にしたとき、クエリ `"get_max_model_len"` と `"max model len"` のどちらがヒットするか。その理由は
18. 索引は既定の `tokenize()`、クエリだけを自作の関数（`_` でも区切る）で区切ったとき、クエリ `"get_max_model_len"` はヒットするか
19. 英語のストップワードを除く処理は、TF、IDF、長さのどれと関係が深いか。除かなかったら点数はどうなるか

## 3. 次にやること

- overlap の値：`evaluate` ができてから実測で決める（Q31）
- 全体の実装が終わったら、`_split_text` をもう一度確認する
- ~~段階2のコードの読解~~、~~コミット~~（2026-10-20 済み）。**index のパートは、これで基本的に終了**
- search：`load` して `retrieve`、`Chunk` → `MinimalSource`。点数0の結果の扱い（Q39）
- **evaluate を実装した後にまとめてやること**（2026-10-20 ユーザーの指示）：
    - `chunk_overlap` の値（0／200／400 などを比べる。Q31）
    - トークン化の比較（丸ごとだけ／部品だけ／両方。1文字の語を捨てるか。Q36、Q46）
    - BM25 のパラメータ（`k1`、`b`）
    - 隠しディレクトリを外すか（Q47。正解データに含まれるかも確かめる）
- `index` を実際に動かすときのデータの置き場所（`data/raw/` は作業ツリーになく、zip のまま）
- エラー処理（「0」の既知の問題を参照）

## 4. README に使えるポイント

- **Chunking strategy**：langchain の `RecursiveCharacterTextSplitter`。Python 用と Markdown 用を使い分け、`.txt` は汎用の区切り。長さは文字数で測る（moulinette の2000文字制約に合わせるため。Q5）。位置は `add_start_index` と `start + len` で求める（Q20）
- **Retrieval method**：BM25（bm25s、`lucene` 方式）。トークン化は識別子を丸ごとと部品の両方で残す（Q35、Q36）。考え方は Lucene の `word_delimiter_graph`（`preserve_original=true`）と同じ、ストップワードは Lucene/Elasticsearch の標準の33語（Q43、Q44）。BM25 のトークンは LLM のトークンとは別物（Q34）
- **Design decisions**：bm25s を選んだ理由（Q1、Q32 の比較表）、対象ファイルの選び方（Q10、Q11）、ソートによる再現性（Q6）、pydantic の `TypeAdapter` で保存する理由（Q9）、終端を含まない形にした理由
- **Challenges**：langchain は位置を返さないので、`find` で探し直していること（Q13）。Python 用の区切りの癖（Q18）。overlap は保証ではなく上限であること（Q19、Q29）。チャンク同士のつながりは保存されず、overlap では参照（He → Alex）を解決できないこと（Q30）。`---` や `` ``` `` だけの3文字のチャンクが6個でき、トークンが0個になること（Q46）
