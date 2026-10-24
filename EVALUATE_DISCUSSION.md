# evaluate 実装の議論メモ（2026-10-21〜）

`evaluate` の実装に関する議論を、ユーザーの質問ごとにまとめたもの。
用途：翌日以降の見返し、取りこぼし防止、README.md（Performance analysis / Design decisions / Challenges）作成の材料。
index と search の議論は `INDEX_DISCUSSION.md`、`SEARCH_DISCUSSION.md` を参照（Q番号は evaluate 側で1から振り直す。ほかを指すときは「index Q45」「search Q8」のように書く）。

ライブラリの挙動は、インストール済みのソースで確認したものだけを書く。

---

## 0. 現在の状態

### 課題の要件（subject v2.0 の VI.6、VII.1）

- `evaluate --student_search_results_path <path> --dataset_path <path>`："Report your own recall@k against a ground-truth dataset, for your own testing."
- **自分の確認用**。審査の recall は moulinette が計算する。**コードから moulinette を import したり呼び出したりしてはいけない**（手で実行して答え合わせに使うのは問題ないと考えられる）
- recall@k の定義（VII.1.1）："For each question, recall@k is the share of its correct sources that you retrieve in your top-k results. A correct source counts as found when one of your results is in the same file and overlaps its character range."
    - 重なりの基準は **IoU 0.05**。別のファイルの結果は数えない（`file_path` は完全一致）
- 合格基準：recall@5 で **docs 80% 以上、code 50% 以上**
- 共通の要件：パスは CLI 引数（ハードコードしない）、長い処理には tqdm、壊れた入力（ファイルがない、壊れた JSON など）でもトレースバックを出さない

### moulinette について分かっていること（`READEME_MOULINETTE.md`）

- コマンド：`evaluate_student_search_results <student_results_path> <dataset_path> [--k 10] [--max_context_length 2000]`
- 出力形式を検証してから、**Recall@1、@3、@5、@10** を計算する
- 入力1：自分の検索結果（`StudentSearchResults` の形）。入力2：正解（`RagDataset` の形。各質問に `question_id`、`question`、`answer`、`sources`）
- 配布物は `moulinette-ubuntu` と `moulinette-fedora` の実行ファイル（Linux 用）。macOS では直接動かない可能性がある（未確認）

### 引き継いだもの

- `search_dataset` の出力：`StudentSearchResults`（search Q8）。`question_id` は入力からコピー済み
- 正解データ：`datasets_public/public/AnsweredQuestions/dataset_{docs,code}_public.json`（search Q11：今は移さない）
- 懸念（CLAUDE.md）：`RagDataset` の `List[AnsweredQuestion | UnansweredQuestion]` で、pydantic の解釈次第で `sources` が落ちる可能性 → ここで確認する
- 未確認（CLAUDE.md）：正解範囲の長さの分布、`last_character_index` が終端を含むかどうか、Answered と Unanswered の `question_id` の一致
- `question_id` で突き合わせるというのは推測（search の議論）。evaluate を同じ仕組みで作り、moulinette と数字を比べて裏付ける

### evaluate の後に戻るタスク（index の「3. 次にやること」より）

- `chunk_overlap` の値、トークン化の比較（丸ごと／部品／両方、1文字の語）、BM25 のパラメータ、隠しディレクトリを外すか
- search の未決事項：点数0の結果の扱い、`search` コマンドの出力（search Q5）

### 実装済み（2026-10-21〜23、コミット `7322134`。evaluate のパートは 2026-10-23 に一旦終了）

| ファイル | 中身 |
|---|---|
| `src/evaluate.py`（新規） | `iou(a, b)`：同じファイルの2つの範囲の IoU（範囲は `[first, last)`、別ファイルなら0）。`evaluate(student_search_results_path, dataset_path) -> dict[int, float]`：k = 1、3、5、10 の recall。定数 `KS`、`MIN_IOU = 0.05` |
| `src/__main__.py` | `evaluate` コマンド。`Recall@1: 0.600 Recall@3: ...` の形で1行に出す（moulinette の出力に合わせた） |
| `tests/test_evaluate.py`（新規、ローカルのみ） | `iou` のテスト3件（部分的な重なり、同一と隣接、別ファイル） |

- **公開データでの結果（`--k 10` で search_dataset）**：

| | Recall@1 | @3 | @5 | @10 | 基準（@5） |
|---|---|---|---|---|---|
| docs | 0.600 | 0.800 | **0.870** | 0.870 | 80% → 合格 |
| code | 0.444 | 0.636 | **0.677** | 0.788 | 50% → 合格 |

- evaluate はコマンド全体で約0.2秒
- moulinette とは比べていない（Linux 用の実行ファイル。docker もない）
- flake8 通過、pytest 6件通過、mypy のエラーは中身が空の `answer`、`answer_dataset` の2件だけ

### 決めたこと

- はっきりしない点は**推測で実装する**（2026-10-21 ユーザーの判断。evaluate は自分の確認用で、厳密なコードレビューの対象ではないと考えられるため）
    - 平均の取り方：質問ごとの recall の平均（課題の文言どおり）。公開データは全問とも正解のソースが1つなので、どちらの取り方でも同じ値になる
    - IoU：範囲は終端を含まない `[first, last)` として計算（自分の `chunks.json` と同じ扱い。正解データの扱いは未確認）
    - 報告する k：moulinette と同じ 1、3、5、10。CLI の引数にはしない
    - 突き合わせ：`question_id`。検索結果がない質問は recall 0。正解の母数は、`sources` を持つ `AnsweredQuestion` だけ
- `RagDataset` で `sources` が落ちる懸念は**問題なし**：公開の AnsweredQuestions は100問すべて `AnsweredQuestion` として読まれ、`sources` が残った（pydantic の union の解釈）
- tqdm は付けない（evaluate は約0.2秒で、長い処理ではない）

- 2026-10-21 追加：`evaluate` は `(一致した質問数, 正解の質問数, recall の辞書)` を返し、コマンドは `Matched 100 of 100 questions` を recall の前に出す（Q2）

### 未決事項

- moulinette の数字との比較（Linux 環境が必要）。2026-10-23：moulinette を展開したが、`moulinette-ubuntu`/`-fedora` は Linux 用の x86-64 の ELF で、この Mac（arm64、macOS）では動かない。docker などもない → **後回し**（ユーザーの決定）。校舎の Linux マシンで、`search_dataset --k 10` → `./moulinette-ubuntu evaluate_student_search_results <結果> <正解> --k 10 --max_context_length 2000` を docs と code で実行し、自作の evaluate（docs 0.870、code 0.677）と比べる。`vllm-0.10.1.zip` と `datasets_public/` は別に持っていく
- エラー処理（エラー処理の段階でまとめて）：ファイルがない（`FileNotFoundError`）、**ファイルの代わりにディレクトリを渡された（`IsADirectoryError`。2026-10-23 実際に起きた）**、壊れた JSON・形が違う（`ValidationError`）
- ~~`--dataset_path` に `UnansweredQuestions` を渡すと `Matched 0 of 0 questions` で recall がすべて0になる~~ → 2026-10-23 決定・実装：**一致が0件なら警告を出し、実行は中止しない**（ユーザーの決定）。警告は標準エラー出力に `Warning: no question_id matched. Check that both files come from the same dataset and that dataset_path is an AnsweredQuestions file.`（別のデータセットどうし、Unanswered を正解として渡した、の両方の原因に触れる）。終了コードは0のまま

---

## 1. 質問ごとのまとめ

### Q1. evaluate に求められる挙動

- 入力：`--student_search_results_path`（`search_dataset` の出力、`StudentSearchResults`）と `--dataset_path`（正解の `AnsweredQuestions`、`RagDataset`。各質問が正解の `sources` を持つ）
- 処理：
    1. 同じ `question_id` どうしで、検索結果と正解を組にする
    2. 正解のソース1つずつについて、上位 k 件の中に「`file_path` が完全一致」かつ「IoU 0.05 以上」のものが1つでもあれば「見つけた」とする。IoU = 重なっている文字数 ÷ 2つの範囲を合わせた文字数
    3. 質問ごとの recall@k = 見つけた正解のソースの数 ÷ その質問の正解のソースの数（VII.1.1 の文言どおり）
    4. 全体の recall@k = 質問ごとの値の平均
    5. moulinette と同じく k = 1、3、5、10 で計算する（上位 k 件だけを使う）
- 出力：recall@1、@3、@5、@10 を画面に出す（"Report"。ファイルに保存する指定はない）
- 守ること：自分の確認用、moulinette を import・呼び出ししない、パスは CLI 引数、壊れた入力でトレースバックを出さない
- はっきりしていないこと（moulinette と数字を比べて確かめる）：
    - 4 の平均の取り方（質問ごとの平均は推測。全ソースをまとめた割合の可能性もある）
    - IoU の細部（`last_character_index` が終端を含むか）
    - 1 の突き合わせが `question_id` か

### Q2. evaluate の読解と、recall@k の理解（2026-10-21）

- **recall@k**：検索システムの成績。たとえは落とし物探し（鍵をなくし、ありそうな場所を k か所挙げてもらう。その中にあれば1、なければ0。100回やって平均）。k は「上から何件目まで見るか」で、大きいほど甘い
    - 1問の recall@k = 上位 k 件で見つけた正解の数 ÷ その質問の正解の総数（正解の総数は正解データの `len(q.sources)`。recall から逆算するものではない）。分母は k ではない（k で割るのは precision）
    - どの正解を見つけたかは関係ない（数だけ）。1 になるのは全部見つけたときだけ
    - 全体の値は**質問について平均**する。k について平均はしない（recall@1、@3、@5、@10 は別々に報告。合格基準は @5 だけを見る）
    - 公開データは全問とも正解が1つ → 各問は 0 か 1。docs の recall@5 = 0.870 は「100問中87問で、上位5件に答えの場所が入っていた」
    - evaluate の k が search の k を上回る場合：存在しない分ははずれ扱い。自動で1にはならず、実力より低く出る → `search_dataset` は `--k 10` で実行する（課題の実行例も moulinette も `--k 10`）
    - 評価されるのは**検索システム**（index + search）。evaluate は採点係
- **ライブラリ**：ranx（公式ドキュメントで確認："Recall is the ratio between the retrieved documents that are relevant and the total number of relevant documents"）などがあるが、**文書 ID の完全一致**が前提。課題の判定は範囲の IoU なので、そのままでは使えない。使うには IoU の判定を自分で書いて ID に変換する必要があり、残りは割り算と平均だけ → 依存を増やさず自作（README の説明に使える）
- **IoU**：2つの範囲の重なりの長さ ÷ 合わせた全体の長さ。0〜1
    - 比べるのは**文字の位置**で、文字列の中身ではない。自分のチャンクと正解の範囲（正解データの作成者が決めたもので、チャンクの区切りとは無関係）を、同じファイルの文字の位置という共通の物差しで比べる
    - 例：同じ文章の中の "hello world" [0, 11) と "world destroyer" [6, 21) → 5 ÷ 21（11 + 15 では重なりを2回数えてしまう）
    - 基準 0.05 は甘め（"retrieving a chunk that covers the right region of the right file is enough"）。かすっただけのものを除くための割合
    - 別のファイルは常に0（課題のルール："A result in a different file never counts"）。内容が似た別ファイルを拾ってもはずれ（指標の限界。README の Challenges に書ける）。意味の評価は answer の側（人間のレビュアー）
    - 位置で見るので、採点が「ほぼ同じだが not が入った別の文」に騙されることはない。一方、検索（BM25）は not をストップワードとして捨て、順番も見ないので、意味の反転に耐性がない。意味を扱えるのは answer（Qwen）。正解を使って answer で絞り込むのはカンニング（search Q2 と同じ）。正当な方法：複数のチャンクを渡す、プロンプト、リランキング、埋め込み検索（加点要素1）
- **`iou` のコード**：
    - `inter`（**分子**）= max(0, 早いほうの終わり − 遅いほうの始まり)。どちらが前でも同じ式で計算できる。`max(0, n)` は n が負なら0（重ならない場合）
    - `union`（**分母**）= a の長さ + b の長さ − inter（重なりを2回数えない）
    - `union > 0` のときだけ割る。0 になるのは2つとも長さ0の範囲のときだけ（`ZeroDivisionError` を避ける）
- **`evaluate` のコード**：
    - `model_validate_json`：JSON → Python のオブジェクト（呼んだクラス）。必須の項目、型、入れ子の中身まで確かめる。余分なキーは無視、型はゆるく変換（lax モード）。逆向き（オブジェクト → JSON）は `model_dump_json`
    - `retrieved`：「質問の ID → 検索結果のリスト」の辞書。ない ID は空のリスト（見つけなかった扱い）
    - `answered`：`AnsweredQuestion` で、`sources` が空でないものだけ（`UnansweredQuestion` で落ちないように、0 で割らないように。mypy の型の絞り込みも兼ねる）
    - `KS = (1, 3, 5, 10)`：recall を計算する k の一覧（moulinette と同じ）。CLI の引数にはしない
    - `any(...)`：1つでも真なら True、空なら False。「上位 k 件のどれか1つでも IoU 0.05 以上か」。`sum` で True を1として数え、見つけた正解の数にする
    - `[:k]` だけで上位 k 件になるのは、`search_dataset` が `sorted=True` で並べているから。出力ファイルに点数はないので、ファイルの並び順が順位になる。並んでいないと recall@1〜@5 が低く出る
- **入力の組み合わせ**：`--student_search_results_path` は `UnansweredQuestions` を検索したものでよい（課題の普通の流れ）。`--dataset_path` は `AnsweredQuestions` でなければならない。公開データの Unanswered と Answered の `question_id` は、件数も順番も完全に一致（docs 100、code 99。CLAUDE.md の未確認事項が解決）
- **対応の確認**：以前は、組み合わせを間違えても recall がすべて0になるだけで区別できなかった → **一致した質問数を出す**ようにした（ユーザーの決定）。docs どうし → `Matched 100 of 100 questions`、docs の結果と code の正解 → `Matched 0 of 99 questions`

---

## 2. 答え合わせしていない確認の質問

1. 正解が3つある質問で、上位5件が2つの正解と重なり、そのうち1つの正解には上位5件のうち2件が重なっていた。recall@5 はいくつか
2. `search_dataset --k 3` の結果で evaluate を実行したとき、recall@5 と recall@10 はどうなるか。それは実力より高いか低いか
3. 正解 `[100, 300)`、検索結果 `[250, 2250)`（同じファイル）の IoU はいくつか。0.05 を超えるか
4. 2000文字のチャンクで、IoU 0.05 を満たすのに最低限必要な重なりは、正解の長さによってどう変わるか（ヒント：union は少なくとも2000）
5. `search_dataset` が `sorted=False` だったら、recall@10 は変わるか。recall@1 はどうか
6. `iou` の `max(0, ...)` を取り除いたら、重ならない2つの範囲でどんな値が返り、recall にどう影響するか
7. `answered` の条件から `q.sources`（空でない）を外したら、どんな入力で何が起きるか
8. `retrieved` を辞書ではなく、毎回 `results.search_results` を先頭から探す形にしたら、何が変わるか（結果と速さ）
9. 別のファイルに同じ文章があった場合、IoU と recall はどうなるか。それは課題のどのルールによるか

## 3. 次にやること

- evaluate のパートは一旦終了（2026-10-23）
- 後回し：
    - moulinette との比較（校舎の Linux マシンで。手順は「0. 未決事項」）
    - エラー処理（全コマンドまとめて。「0. 未決事項」の一覧を参照）
- evaluate ができたので戻れるタスク：
    - index の調整：`chunk_overlap`、トークン化の比較、BM25 のパラメータ、隠しディレクトリ（`INDEX_DISCUSSION.md` の「3. 次にやること」）
    - search の未決事項：点数0の結果の扱い、`search` コマンドの出力（search Q5）
- まだ手をつけていないコマンド：`answer`、`answer_dataset`

## 4. README に使えるポイント

- **Performance analysis**：公開データでの recall（`search_dataset --k 10`、`max_chunk_size=2000`、overlap 200、BM25 の既定値）

    | | Recall@1 | @3 | @5 | @10 |
    |---|---|---|---|---|
    | docs | 0.600 | 0.800 | 0.870 | 0.870 |
    | code | 0.444 | 0.636 | 0.677 | 0.788 |

    基準（@5：docs 80%、code 50%）を満たす。調整後の数字はここに追記する。`search_dataset` は docs 100問でコマンド全体約2.5秒（90秒の制限に対して十分）
- **Design decisions**：
    - recall@k を自作した理由：ranx などの標準ライブラリは文書 ID の完全一致が前提で、課題の判定（同じファイルかつ範囲の IoU 0.05 以上）は自分で書く必要がある。残りは割り算と平均だけなので依存を増やさなかった（Q2）
    - moulinette に合わせたこと：k = 1、3、5、10、出力の形式、質問ごとの平均、`question_id` での突き合わせ
    - 取り違えに気づけるよう、一致した質問数を出し、0件なら警告する（Q2）
- **Challenges**：
    - 採点は位置だけを見るので、内容が似た別のファイルを拾ってもはずれになる（指標の限界）
    - BM25 は `not` をストップワードとして捨て、順番も見ないので、意味の反転を区別できない。意味を扱うのは answer（Qwen）の役目（Q2）
    - moulinette は Linux 用の x86-64 の実行ファイルで、Apple Silicon の Mac では動かせなかった
    - macOS はパスの大文字と小文字を区別しないので、手で打ったパスの間違い（`ANsweredQuestions`）が Mac では動いてしまう。Linux では動かない
