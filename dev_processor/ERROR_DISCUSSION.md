# エラー処理の議論メモ（2026-10-28〜）

全コマンドのエラー処理に関する議論と実装を、ユーザーの質問ごとにまとめたもの。
用途：翌日以降の見返し、取りこぼし防止、README.md（Design decisions / Challenges）作成の材料。
ほかの議論は `INDEX_DISCUSSION.md`、`SEARCH_DISCUSSION.md`、`EVALUATE_DISCUSSION.md`、`ANSWER_DISCUSSION.md` を参照（ほかを指すときは「index Q24」のように書く）。

---

## 0. 現在の状態

### 課題の要件（subject v2.0 の VI.6）

> Include progress bars (tqdm) for long-running operations, and handle degenerate inputs (empty query, nonsensical query, k=0, missing files, malformed JSON) gracefully. The CLI is tested with such edge cases and must never crash with an unhandled traceback.

- コマンドを名指ししていない → **CLI 全体**が対象。`--k` を受け取る search、search_dataset、answer の3つとも k=0 で落ちてはいけない
- 求められているのは「gracefully に扱う（トレースバックで落ちない）」まで。エラーにするか空の結果を返すかは指定なし

### 実装済み（2026-10-28、コミットはまだ）

| ファイル | 中身 |
|---|---|
| `src/__main__.py` | `main()`：`fire.Fire(Orchestrator)` を囲む最後の砦。`positive_int(name, value, maximum=None)`：正の整数の確認。`question_of(query)`：空のクエリの確認と `UnansweredQuestion` への変換。`MAX_CHUNK_SIZE = 2000` |
| `src/index.py` | `raw_dir` の確認、対象ファイル0件の確認、1ファイルずつの読み込みエラーで警告して飛ばす、読めたチャンク0件の確認、`file_path` を `os.path.relpath` で作る |
| `src/chunker.py` | `CHUNK_OVERLAP = 200`、overlap は `min(CHUNK_OVERLAP, max_chunk_size // 2)`。位置が本文と合わないチャンクを飛ばす |
| `src/search.py` | `chunks.json` がなければ分かりやすいメッセージ。`k` をチャンク数で切り詰める |

### 決めたこと

- **`--k` が正の整数でなければ、必ずエラーメッセージを出して終了する**（search、search_dataset、answer のすべて。ユーザーの決定）。`0`、負の数、`abc`、`2.5`、`True` を弾く
- **`k` がチャンク数より大きいときは、エラーにせず切り詰める**（bm25s は `ValueError` を出すため）
- **空のクエリ（空白だけを含む）はエラー**
- **`--max_chunk_size` は 1〜2000**（課題 VI.1 "Do not go above it"。moulinette は2000文字を超えるソースがあると出力全体を無効にする）
- **index の読み込みエラーは index Q24 の方針どおり**：全体に関わるもの（`raw_dir` がない・ディレクトリでない・対象が0件）はエラーにして何も保存しない。1ファイルのもの（`UnicodeDecodeError`、`OSError`）は警告を出して飛ばす
- **CRLF は今のまま**（ユーザーの決定。Q3）
- メッセージはすべて**標準エラー出力に1行**、終了コードは1（Ctrl+C は130）

### 未決事項

- `make run` と `make debug` に `ARGS` を足すか（Q6。提案済み、返事待ち）
- 最後の砦が pdb の post-mortem を止めてしまう点、pdb の `q` で `Error:`（中身なし）と出る点（Q6）
- 試していないもの：Ctrl+C、モデルのダウンロードの失敗（ネットがない）、`bm25/` だけが欠けた索引、`chunks.json` が壊れた索引、読み取り専用の `save_directory`

---

## 1. 質問ごとのまとめ

### Q1. どんなエラーが起こりうるか（これまでのメモと実測から）

- メモに記録してあったもの：
    - index Q24・index の既知の問題：`--max_chunk_size` 200未満で overlap の `ValueError`、絶対パスの `raw_dir` で `file_path` が `data/raw/...` にならない、`UnicodeDecodeError`・`PermissionError` で全体が止まる、`raw_dir` がない・0件で「成功」と出る（BM25 を足してからはトレースバック）、CRLF の位置ずれ、`find` が -1 を返す場合の防御がない、保存先がファイル（`FileExistsError`）や権限なし（`OSError`）
    - search の未決事項：`k` が0以下・チャンク数より大きい、`--k abc`、索引がない（`FileNotFoundError`）・`bm25/` だけない・`chunks.json` が壊れている（`ValidationError`）・件数不足（`IndexError`）、データセットがない・壊れた JSON、保存先が作れない
    - evaluate の未決事項：ファイルがない、**ファイルの代わりにディレクトリ（`IsADirectoryError`。2026-10-23 実際に起きた）**、壊れた JSON・形の違うファイル
    - CLAUDE.md の Fire の注意点：Fire は型ヒントで変換しない（`--max_chunk_size abc` は文字列）、数字だけのクエリは int
- **実測（修正前）**：壊れた入力を一通り試し、**トレースバックが16件**

| 入力 | 修正前の結果 |
|---|---|
| `search "lora" --k -2` / `--k abc` / `--k 2.5` | トレースバック（`ValueError` / `TypeError`） |
| `search "lora" --k 999999` | トレースバック（bm25s：k がチャンク数より大きい） |
| `search "lora" --k 0` | 何も出さずに終了コード0 |
| `search "" --k 3` | 点数0のチャンクを返す |
| `--processed_dir /nonexistent` | `FileNotFoundError` |
| データセットがない／ディレクトリ／壊れた JSON／形が違う | `FileNotFoundError` / `IsADirectoryError` / `ValidationError` |
| `--save_directory` がファイル | `FileExistsError` |
| `index --raw_dir /nonexistent` | bm25s の `ValueError: max() iterable argument is empty` |
| `index --max_chunk_size 100` / `abc` / `0` | `ValueError`（overlap 200 > 100）/ `TypeError` / `ValueError` |
| evaluate、answer_dataset の壊れた入力 | トレースバック |
| 引数の不足、知らないコマンド、`--help` | トレースバックなし（Fire が処理。Q5） |

### Q2. 方針：最後の砦と入口での確認

- **最後の砦**（`__main__.main()`）：
    ```python
    try:
        fire.Fire(Orchestrator)
    except KeyboardInterrupt:
        sys.exit(130)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        print(f"Error: invalid {e.title} data"
              f"{f' at {where}' if where else ''}: {first['msg']}",
              file=sys.stderr)
        sys.exit(1)
    # FireExit (after --help or a usage error) is a SystemExit, not caught.
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    ```
    - どんな例外でもトレースバックを出さない保証になる
    - pydantic の `ValidationError` はそのままだと数行の長いメッセージ（`For further information visit https://errors.pydantic.dev/...`）になるので、最初のエラーの「モデル名・場所・要点」だけを1行にする。例：`Error: invalid RagDataset data at rag_questions: Field required`、`Error: invalid RagDataset data: Invalid JSON: key must be a string at line 1 column 2`
    - **以前の「`fire.Fire` を try/except で囲まない」方針**（Fire は `--help` の後も `FireExit` を投げるため）は、`FireExit` が `SystemExit` の子クラスで `Exception` に含まれないことを確かめて解消した（`issubclass(fire.core.FireExit, SystemExit)` が True）
- **入口での確認**（`__main__.py`）：最後の砦だけだとメッセージが分かりにくい（`'>' not supported between instances of 'str' and 'int'` など）ので、CLI の境界で先に確かめる
    - `positive_int`：`isinstance(value, bool)` を先に弾く（`True` は `int` の子クラスなので `isinstance(True, int)` が True になるため）。`maximum` で上限も見る
    - `question_of`：`str(query)` にしてから `.strip()` で空か確かめる（Fire は数字だけのクエリを int で渡す）
- 入口の確認は「外から来る、間違っているかもしれない入力」なので `if` と例外で書く（`assert` は `-O` で消えるので使わない。answer の議論の `assert` の話と対になる）

### Q3. CRLF とは、なぜ今のままにしたか

- **改行の書き方の種類**。LF は `\n`（1文字、Linux・macOS）、CRLF は `\r\n`（2文字、Windows）。CR（Carriage Return）は先頭に戻す、LF（Line Feed）は1行送る、というタイプライターの動きが由来
- Python の `read_text()` は `\r\n` を `\n` に変換するので、CRLF のファイルでは行が変わるたびに1文字ずつ位置がずれる（`a b \r \n c d` の `c` が 4 → 3）
- vLLM の対象の拡張子（`.py`、`.md`、`.txt`）で CRLF のファイルは**4つ**：`tests/test_seed_behavior.py`（24行）、`tests/test_embedded_commit.py`（8行）、`tests/quantization/test_cpu_offload.py`（76行）、`vllm/model_executor/layers/quantization/utils/__init__.py`（3行）
- 公開のグラウンドトゥルースには、この4ファイルは出てこない
- index も answer も `read_text()` で読むので、**自分の中では位置がそろう**。moulinette がどちらの数え方かは分からない → **今のまま**（ユーザーの決定。Claude のおすすめ）。`open(..., newline="")` で `\r` を残す案は採らない

### Q4. k=0 は全コマンドで落ちてはいけないのか

- VI.6 の文はコマンドを名指しせず「The CLI is tested with such edge cases」。`--k` を受け取る search、search_dataset、answer のすべてが対象と読める
- 同じ文の「空のクエリ」は search と answer、「ファイルがない」「壊れた JSON」は search_dataset、evaluate、answer_dataset、index（索引の読み込み）が対象
- 決定：3つとも**エラーメッセージを出して終了**（`Error: --k must be a positive integer, got 0`）

### Q5. Fire が出すエラーと、こちらの最後の砦の分担

- 引数が足りないとき（`search` だけ）の表示は、**最後の砦を入れる前と同じ**（コミット済みのコードで確認。終了コードも2）：
    ```
    ERROR: The function received no value for the required argument: query
    Usage: __main__.py search QUERY K <flags>
      optional flags:        --processed_dir

    For detailed information on this command, run:
      __main__.py search --help
    ```
    - ユーザーは「Fire を囲った弊害でヘルプが出なくなった」と考えたが、Fire はもともと引数の不足では短い Usage だけを出し、詳しいヘルプは `--help` で出す
- **この表示はこちらの `except Exception` では捕まえていない**（ユーザーの指摘どおり。色で見分けられる）：
    - `fire/core.py`：`if component_trace.HasError(): _DisplayError(component_trace); raise FireExit(2, component_trace)`
    - `_DisplayError` が `formatting.Error('ERROR: ')` で出す。`fire/formatting.py`：`termcolor.colored(text, color='red', attrs=['bold'])` → **赤い太字**
    - `FireExit` は `SystemExit` の仲間なので、`except Exception` を素通りする

| 表示 | 出しているもの | 色 | 終了コード |
|---|---|---|---|
| `ERROR: ...` ＋ `Usage: ...` | Fire（引数の不足、知らないコマンドなど、Fire が見つけた問題） | 赤い太字 | 2 |
| `Error: ...`（1行） | こちらの最後の砦（コマンドの中で起きたエラー） | 色なし | 1 |

### Q6. `make debug` がほぼ動かない

- `debug: uv run python -m pdb -m src` は引数を渡せないので、`c` で続行しても Fire のヘルプが出て終わるだけ（`make run` も同じ）
- pdb 自体は引数を渡せば使える：`uv run python -m pdb -m src search "lora adapters" --k 2` → `b src/search.py:33` → `c` → 止まる → `p k, question.question` → `(2, 'lora adapters')`
- 提案（返事待ち）：`run` と `debug` に `$(ARGS)` を付ける。`make debug ARGS='search "lora adapters" --k 2'`。`ARGS` なしなら今と同じ
- **最後の砦との相性**：
    - 最後の砦がすべての例外を捕まえるので、pdb の post-mortem（エラーが起きた場所で止まる機能）が働かない。原因を調べるときはブレークポイントで止める使い方になる
    - pdb の中で `q` すると、pdb の終了の合図（`BdbQuit`、`Exception` の子クラス）まで捕まえて `Error:`（中身なし）と出る。害はない
    - デバッグのときだけ最後の砦を外す仕組みも作れるが、要らないと判断（Claude の提案。未決）

### Q7. 実装の詳細（ファイルごと）

- **`__main__.py`**：Q2 のとおり。各コマンドの最初で `question_of`、`positive_int` を呼ぶ。`index` は `positive_int("max_chunk_size", max_chunk_size, MAX_CHUNK_SIZE)`
- **`index.py`**：
    ```python
    if not Path(raw_dir).is_dir():
        raise NotADirectoryError(f"raw_dir is not a directory: {raw_dir}")
    files = collect_files(Path(raw_dir))
    if not files:
        raise ValueError(f"no .py, .md or .txt files under {raw_dir}")
    ...
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            tqdm.write(f"Warning: skipped {path}: {e}", file=sys.stderr)
            continue
        file_path = Path(os.path.relpath(path)).as_posix()
    ...
    if not sources:
        raise ValueError(f"no readable text under {raw_dir}")
    ```
    - 警告は `tqdm.write` で出す（進捗バーの表示を崩さないため）
    - 確認はすべて保存より前なので、エラーのときは何も保存しない
    - `os.path.relpath`：作業ディレクトリからの相対パス。相対の `raw_dir` ならそのまま（`./data/raw` も `data/raw` に正規化）、作業ディレクトリの中を指す絶対パスなら `data/raw/...`、外なら `../../...`
- **`chunker.py`**：
    - overlap を `min(CHUNK_OVERLAP, max_chunk_size // 2)` にした。langchain は overlap がチャンクより大きいと `ValueError`。課題 VI.1 は "Smaller chunks are fine" なので、小さいチャンクでも動かす。既定の2000では200のまま
    - `if text[start:start + len(doc.page_content)] != doc.page_content: continue`：langchain は開始位置を `find` で探し直していて、見つからないと -1（index Q13）。位置が本文と合わないチャンクは保存しない（vLLM では0件）
- **`search.py`**：
    - `if not (out / CHUNKS_FILE).is_file(): raise FileNotFoundError(f"no index under {processed_dir}; run the index command first")`
    - `k=min(k, len(sources))`（bm25s は k がチャンク数より大きいと `ValueError`）
- evaluate、answer_dataset、answer は個別の処理を足していない（ファイルのエラーと pydantic の検証は最後の砦で1行になる）

### Q8. 修正後の確認

- 修正前の16件を含め、壊れた入力30件以上で**トレースバックは0件**。代表的なメッセージ：

| 入力 | 修正後 |
|---|---|
| `search "" --k 3` | `Error: the query must not be empty` |
| `search "lora" --k 0` / `abc` / `True` | `Error: --k must be a positive integer, got 0` / `'abc'` / `True` |
| `search "lora" --k 999999` | 正常（チャンク数に切り詰めて表示） |
| `--processed_dir /nonexistent` | `Error: no index under /nonexistent; run the index command first` |
| データセットがない | `Error: [Errno 2] No such file or directory: '/nonexistent.json'` |
| ディレクトリを渡した | `Error: [Errno 21] Is a directory: '...'` |
| 壊れた JSON | `Error: invalid RagDataset data: Invalid JSON: key must be a string at line 1 column 2` |
| 形が違う | `Error: invalid RagDataset data at rag_questions: Field required` |
| `--save_directory` がファイル | `Error: [Errno 17] File exists: '...'` |
| `index --raw_dir /nonexistent` | `Error: raw_dir is not a directory: /nonexistent` |
| 空のディレクトリ | `Error: no .py, .md or .txt files under ...` |
| `--max_chunk_size 0` / `abc` / `3000` / `True` | `Error: --max_chunk_size must be a positive integer up to 2000, got ...` |
| `--max_chunk_size 100` | 正常（overlap 50） |
| バイナリの `.py`、読み取り権限のない `.md` | `Warning: skipped ...: 'utf-8' codec can't decode byte 0xff ...` / `[Errno 13] Permission denied` を出して残りを索引にする |

- 絶対パスの `raw_dir`（`$(pwd)/data/raw`）で作った `chunks.json` が、相対パスのものとも、**修正前のものとも、バイト単位で同じ**（14638チャンク）
- docs の recall は変わらず（Recall@1 0.600、@3 0.800、@5 0.870、@10 0.870）
- `make lint`（flake8、mypy）は通る

---

### Q9. ファイルを書くオペレーションが途中で失敗したら（2026-10-30）

- **事実**：index は「`chunks.json` を書く → BM25 を作る → `bm25/` を書く」の順。BM25 を作る段階で落ちると、`chunks.json` だけ新しく、`bm25/` は古いままになる
    - `lora.md` だけで確認：2000 で index した後に `--max_chunk_size 1` で index → `chunks.json` は15,148件（1文字ずつ）、`bm25/` は15チャンク分のまま。`search "lora" --k 3` がエラーにならず `[7:8]`、`[5:6]`、`[14:15]` を返す（古い BM25 の番号で新しい `chunks.json` を引いている）
    - vLLM 全体で `--max_chunk_size 1`：チャンク分割に8分17秒（5分の制限を超える）、20,147,166チャンク、BM25 で 0÷0 の RuntimeWarning の後に `ValueError: max() iterable argument is empty`。`chunks.json` は 2.5 GB に上書きされ、`bm25/` は前回のまま
- 同じ名前のファイルに毎回上書きする（`chunks.json` は `write_bytes`、`bm25/` は bm25s の `save` が決まった5つの名前で書く）
- **決めたこと（ユーザー）**：ファイルを書くオペレーション（index、search_dataset、answer_dataset）では、エラーが出たときに必ず、出力先のファイルの確認を促すワーニングを出す。**まだ実装しない**

### Q10. `--max_chunk_size` が1や2のとき（2026-10-30）

- **Indexing の時間は割り切る（ユーザーの決定）**：課題の5分の制限はふつうの設定（既定の2000）の話と読む。避けるには下限を設けるしかないが、何文字なら意味があるかに根拠がなく、課題にも下限はない。トークンが0個になるかはトークン化するまで分からないので、事前に安く見分ける方法もない
- **事実**：`1` のとき `chunks.json` は空にならない（2000万件）。空になるのは全チャンクのトークン（BM25 の語彙）。1文字のトークンを `tokenize` で捨てるため。`chunks.json` が空（読めたチャンクが0件）の場合は、すでに `no readable text under ...` のエラーで、何も保存しない
- **決めたこと（ユーザー）**：全チャンクのトークンが0個なら、ワーニングではなく**エラー**にする（BM25 が作れず、続けても使える索引ができないため）。確認は **`chunks.json` を書く前** に置く（Q9 の「片方だけ新しくなる」問題もこのケースでは起きなくなる）。メッセージの例：`no searchable tokens; --max_chunk_size 1 is too small`。**まだ実装しない**

### Q11. ファイル操作の失敗（2026-10-30）

- **大前提（ユーザーの決定）**：オペレーション上のファイル操作の失敗は、すべて捕まえる
- 種類（Mac で確認）：ない（`FileNotFoundError`）、ディレクトリだった（`IsADirectoryError`）、途中がファイル（`NotADirectoryError`）、名前がすでにある（`FileExistsError`、mkdir）、権限（`PermissionError`）、読み取り専用（`OSError`）、名前が長すぎる（`OSError`）、ディスクがいっぱい（`OSError`、未確認）。ここまではすべて `OSError` の仲間。`UnicodeDecodeError`（`ValueError` の仲間）と `MemoryError` は違う
- メモリ不足は、多くの場合 OS がプロセスを強制終了するので、Python では捕まえられない（一般的な知識、未確認）
- 課題に UTF-8 やエンコードの記述はない。vLLM 0.10.1 の対象1969ファイルは、すべて UTF-8 で読める
- **index でファイルが読めないとき（権限、UTF-8 でない）**：今の「その場で `Warning: skipped <パス>: <理由>` を出して飛ばす」でよい（ユーザーの決定）
- **index の保存先（`processed_dir`）が書けないとき（権限がない、ディレクトリではなくファイルのパス、ディスクがいっぱい）**：ファイル操作の失敗と同じ様式で扱う（ユーザーの決定）。読み込みと違って飛ばして続けることはできないので、捕まえて1行のエラーで止め、Q9 の「出力先の確認を促すワーニング」を出す、という解釈で記録（未実装）
- **`processed_dir` のパスの扱い（ユーザーが実際に試して決定）**：
    - 途中に拡張子つきの名前（例：`out.json/x`）があっても、存在しなければディレクトリとして作られるので問題ない → スルー
    - 最後の要素が**存在するファイル**のとき（`mkdir` で `FileExistsError`）だけ、ちゃんと捕まえる（未実装）
    - 存在しないパスは、ディレクトリとして作られるので今のまま
- **answer 系での raw のファイルの読み直し**：ふつうの流れなら失敗しない。ただ、外から渡された answer_dataset の入力、作業ディレクトリの違い、index の後の書き換えでは失敗しうる（未決）

### Q12. `except Exception` を外して、また戻した（2026-10-30〜31）

- 2026-10-30：「何でも1行にするだけでは、適切に対処したとは言えない」として外した（ユーザーの決定）。入口の確認や `raise` で自分で出すエラーも、トレースバックになった
- 2026-10-31：「一旦完成させる」ため、元の最後の砦に戻した（ユーザーの決定）。Q9〜Q11 で決めた個別の扱い（確認を促すワーニング、トークンが0個のエラー、`processed_dir` のパスの誤り）は未実装のまま
- `processed_dir` のパスの誤りは、`FileExistsError` と `NotADirectoryError` の共通の親が `OSError` しかなく、`OSError` でまとめると権限やディスクの問題まで「パスが違う」と出てしまう。2つをタプルで捕まえる案を出したところで、この判断になった

### Q13. Q9〜Q11 と点数0の結果を実装（2026-10-31）

- **Q9（書き込み失敗のワーニング）**：index は BM25 を作り終えてから書くように順番を変えた（失敗しうる処理はすべて書く前に済む）。書き込み（`chunks.json`、`bm25/`）を `try` で囲み、失敗したら `Warning: saving the index failed; the files under <dir> may be incomplete. Run index again.` を出して例外を投げ直す。search_dataset と answer_dataset も `write_text` を同じように囲む（`Warning: saving failed; <path> may be incomplete.`）。Ctrl+C も含めるため `except BaseException`
- **Q10（トークンが0個）**：`if not any(tokens)` なら `no searchable words in the chunks; --max_chunk_size N may be too small`。保存の前なので何も書かない（`processed_dir` の mkdir だけは先に済んでいるので、空のディレクトリは残る）
- **Q11（`processed_dir` のパスの誤り）**：`mkdir` を index の最初（ファイル収集の後、チャンク分割の前）に移し、`FileExistsError` と `NotADirectoryError` をタプルで捕まえて `processed_dir is not a directory path (a file is in the way): <path>`
- **点数0の結果**：bm25s が返した点数0のヒットを捨てる。moulinette の `--k` は「質問ごとのソースの最大数」なので、k 件より少なくてよい。単一の `search` で0件なら、標準エラー出力に `No source contains a word of the query.`
- **確認**：上の4つとも動作を確認。recall は変わらず（docs @5 0.870、code @5 0.677）。公開データでは全問が10件のまま（点数0のヒットはなかった）
- answer で0件のときは、空のコンテキストで Qwen を呼ぶ（試していない）

## 2. 答え合わせしていない確認の質問

1. `positive_int` で `isinstance(value, bool)` の確認を `isinstance(value, int)` より後に書いたら、`--k True` はどうなるか
2. `except Exception` の代わりに `except BaseException` にしたら、`--help` はどうなるか
3. `index` の読み込みエラーで `OSError` だけを捕まえ、`UnicodeDecodeError` を書かなかったら、バイナリの `.py` はどうなるか（ヒント：`UnicodeDecodeError` は `ValueError` の子クラス）
4. `k=min(k, len(sources))` を入れずに `--k 999999` を渡したら、最後の砦はどんなメッセージを出すか
5. 確認を保存の後に書いたら、`raw_dir` が空のとき `processed_dir` に何が残るか
6. Fire の `ERROR:` と、こちらの `Error:` の終了コードはそれぞれいくつで、スクリプトから見分けるにはどうするか
7. CRLF のファイルを `open(..., newline="")` で読むようにしたら、index と answer のどちらも変えないといけないのはなぜか

## 3. 次にやること

- `make run`、`make debug` の `ARGS`（Q6、返事待ち）
- 試していないもの（Ctrl+C、モデルのダウンロードの失敗、`bm25/` だけが欠けた索引、壊れた `chunks.json`、読み取り専用の保存先）を確かめるか
- ファイルを書くオペレーションで、エラー時に出力先の確認を促すワーニングを出す（Q9、未実装）
- index で全チャンクのトークンが0個ならエラー。確認は保存の前（Q10、未実装）
- コミット

## 4. README に使えるポイント

- **Design decisions**：CLI の境界で入力を確かめ（Fire は型ヒントで変換しないため）、最後の砦で残りをすべて1行のメッセージにする二段構え。`k` がチャンク数を超えたら切り詰め、0以下ならエラー。`--max_chunk_size` は2000まで（moulinette の上限）。index は全体のエラーなら何も保存せず、1ファイルのエラーなら飛ばす
- **Challenges**：Fire が `True`/`5` を Python の値に、`true`/`abc` を文字列にすること。`True` が `int` の子クラスであること。`FireExit` が `SystemExit` の仲間で、`except Exception` で `--help` を壊さずに済むこと。CRLF のファイルの位置の数え方が moulinette と合うか分からないこと
