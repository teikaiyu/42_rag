# index 実装の議論メモ（2026-10-15〜16）

`index` コマンドの実装を始めてからの議論を、ユーザーの質問ごとにまとめたもの。
用途：翌日以降の見返し、取りこぼし防止、README.md（Chunking strategy / Design decisions / Challenges）作成の材料。

ライブラリの挙動はすべて、インストール済みのソース（langchain-text-splitters 1.1.3、pydantic 2.13.5）で確認したもの。

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
- **コミットはまだ**

### 決めたこと

- 検索ライブラリは **bm25s**（段階2で、ソースを確認してから導入）
- 進め方は段階的に。段階1（保存まで）→ 段階2（BM25 の索引）
- 対象ファイルは拡張子 `.py`、`.md`、`.txt`。拡張子のないファイルは除外（Q10、Q11）
- 分割器は拡張子をキーにした辞書。用意し忘れた拡張子は `KeyError` で気づける（Q16）

### 仮決定（未決事項として残っているもの）

- `last_character_index` は終端を含まない（`text[first:last]` で本文が取れる）
- `chunk_overlap` は langchain の既定の200のまま
- Python 用の区切りリストはそのまま（癖は Q18 を参照）
- 隠しディレクトリ（`.github`、`.buildkite` など）も対象に含める

### 既知の問題（エラー処理の段階で対応）

- `--max_chunk_size` が200未満だと ValueError（overlap 200 > chunk_size、Q4）
- `--raw_dir` に絶対パスを渡すと、`file_path` が `data/raw/...` の形にならない
- 存在しない `raw_dir`、UTF-8 でないファイルは未処理
- `find` が `-1` を返した場合の防御がない（Q13）
- 検索結果を出力するときは、`Chunk` から `text` を除いて `MinimalSource` に詰め替える（moulinette が余分な項目を許すかは未確認）

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

## 3. 次にやること

- A の残り：`build_index` の残り（tqdm、`mkdir`、`as_posix`）、`Orchestrator.index` と Fire のつながり
- 段階2：bm25s のソースで挙動を確かめ（トークン化を差し替えられるか、save/load）、BM25 の索引を足す
- 未決事項：overlap の値、Python 用の区切りの調整、トークン化、隠しディレクトリ
- エラー処理（「0」の既知の問題を参照）

## 4. README に使えるポイント

- **Chunking strategy**：langchain の `RecursiveCharacterTextSplitter`。Python 用と Markdown 用を使い分け、`.txt` は汎用の区切り。長さは文字数で測る（moulinette の2000文字制約に合わせるため。Q5）。位置は `add_start_index` と `start + len` で求める（Q20）
- **Design decisions**：bm25s を選んだ理由（Q1）、対象ファイルの選び方（Q10、Q11）、ソートによる再現性（Q6）、pydantic の `TypeAdapter` で保存する理由（Q9）、終端を含まない形にした理由
- **Challenges**：langchain は位置を返さないので、`find` で探し直していること（Q13）。Python 用の区切りの癖（Q18）。overlap は保証ではなく上限であること（Q19）
