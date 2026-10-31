# answer 実装の議論メモ（2026-10-24〜）

`answer` と `answer_dataset` の実装に関する議論を、ユーザーの質問ごとにまとめたもの。
用途：翌日以降の見返し、取りこぼし防止、README.md（Design decisions / Challenges / prompt strategy）作成の材料。
ほかの議論は `INDEX_DISCUSSION.md`、`SEARCH_DISCUSSION.md`、`EVALUATE_DISCUSSION.md` を参照（Q番号は answer 側で1から振り直す。ほかを指すときは「search Q8」のように書く）。

ライブラリの挙動は、インストール済みのソースや公式ドキュメントで確認したものだけを書く。

---

## 0. 現在の状態

### 課題の要件（subject v2.0 の V.4、VI.3、VI.5、VI.6、VI.7.2）

- モデル：**`Qwen/Qwen3-0.6B`**（既定）。ほかのモデルも使えるが、Qwen3-0.6B で全部が動くこと
- "Pass the retrieved context to the model **within its token budget**, and produce structured JSON following the provided pydantic models."
- よい答えの条件（VI.3）：一貫していて分かりやすい／取ってきたソースに基づき、大きな幻覚がない（grounded）／質問に答えている
    - "grading prioritizes retrieval quality, **grounding and prompt strategy** over perfect final phrasing"。Qwen3-0.6B には推論の限界があり、完全でなくてもよい
- コマンド（VI.6）：
    - `answer <query> --k <int>`："Answer a single query using the retrieved context."
    - `answer_dataset --student_search_results_path <path> --save_directory <dir>`：`StudentSearchResultsAndAnswer` の JSON ファイルを作る
- 出力（VI.5）：`StudentSearchResultsAndAnswer`（`search_results` は `MinimalAnswer` のリスト：`question_id`、`question`、`retrieved_sources`、`answer`。それに `k`）
- 実行例（VI.7.2 の手順4）：
    ```
    uv run python -m src answer_dataset
      --student_search_results_path data/output/search_results/UnansweredQuestions/dataset_docs_public.json
      --save_directory data/output/search_results_and_answer/UnansweredQuestions
    Loaded 100 questions ... Processed 100 of 100 questions
    Saved student_search_results_and_answer to .../UnansweredQuestions/dataset_docs_public.json
    ```
- 共通：長い処理には tqdm、パスは CLI 引数、壊れた入力でトレースバックを出さない
- answer の時間制限は書かれていない（制限があるのは index の5分と search の90秒）
- ライブラリは自由（"Beyond the tools required above, you may use any library you like."）

### 進め方の変更（2026-10-25）

- **下の「コアの部分」の実装は破棄した**（`src/answer.py` を削除。コミットはしていなかった）。ユーザーの指示：answer は**ユーザーと共同で、コードを1行ずつ**作る。Claude が先に全部書かない
- transformers と PyTorch の追加（`pyproject.toml`、`uv.lock`）は残している
- 下の記録は、試したときに分かった事実（テンプレート、速さ、型ヒントの癖など）の参考として残す

### 共同で決めた設計（2026-10-25〜）

- `Orchestrator.answer(query, k, processed_dir="data/processed")`（ユーザーが作成）：`UnansweredQuestion(question=str(query))` → `search(...)` → `answer(...)` → 表示。残り：`-> None`、表示の形（`print(res)` だと pydantic の表示がそのまま出る）
- `src/answer.py`（ユーザーが作成中）：モデルの読み込みなどはクラス `SmallLLMModel` に任せ、`answer` 関数がそれを使う
    - **クラスにする理由**：モデルは一度読み込んだら持ち続ける「状態」。search Q8 の「状態を持つクラスは作らない」は「データのやりとりはデータモデルに任せられる」からで、モデルは例外として筋が通る
    - **pydantic の `BaseModel` は継承しない**：torch のモデルや tokenizer は pydantic の型として持てない。課題 V.4 "Service or orchestration classes … do not have to be pydantic."
    - **`data_models.py` には移さない**：役割が違う（データの形 vs 処理の担当）。さらに `data_models.py` は全コマンドが import するので、torch と transformers の import（約3秒、実測）が search などにも乗ってしまう。`answer.py` に置く（ユーザーの了承）
- **モデルの渡し方は案A**：`answer(retrieved: MinimalSearchResults, llm: SmallLLMModel) -> MinimalAnswer`。呼ぶ側がモデルを1回作って渡す（`answer_dataset` は1回作って使い回す）。案B（クラスのメソッドにする）、案C（モジュールの中で1回だけ作って覚えておく）は採らない
- **`answer` 関数の流れ**：1. 本文を取り出す（`data/raw/` から `text[first:last]`。`answer_dataset` でも使うので小さな関数に）→ 2. 番号とファイルパス付きで資料を並べる → 3. system と user のメッセージを作る → 4. `llm` で生成して文字列をもらう → 5. `MinimalAnswer`
- **境目は案ア**：`answer` 関数が 1〜3 と 5（プロンプト作り、RAG の部分）、`SmallLLMModel` は 4 だけ（メッセージ → テンプレート → トークン化 → 生成 → 文字列）。torch や transformers の細かい話はクラスに閉じ込め、評価される「grounding と prompt strategy」は `answer` 関数に集まる
- 語彙表（Qwen の tokenizer、約15万語）が要るのは手順4だけ。手順3はただのリストと文字列。tokenizer はモデルと一緒に `SmallLLMModel` を作るときに1回読む。BM25 の語彙とは別物
- `read_source(source: MinimalSource) -> str`（Claude が作成、2026-10-25）：`Path(file_path).read_text(encoding="utf-8")[first:last]`。index と同じ読み方でないと位置がずれる（`read_text` は `\r\n` を `\n` に変える）。`lora.md` の15チャンクすべてで、取り出した本文がチャンクの本文と完全一致
- `SmallLLMModel` の外から見た形（2026-10-25 決定）：
    ```python
    class SmallLLMModel:
        def __init__(self, model_name: str = MODEL) -> None: ...      # 作るときに tokenizer とモデルを読み込む
        def generate(self, messages: list[dict[str, str]]) -> str: ...  # メッセージのリスト → 答えの文章
    ```
    - `messages` はチャットのテンプレートが受け取る `{"role": ..., "content": ...}` のリスト（ユーザーの下書きは `str` だった）
    - 引数は `model` ではなく `model_name`（読み込んだモデル本体の `self.model` と紛れないように）。モデル名を変えられるのは課題の「ほかのモデルも可」に合う → 読み込みは汎用の `AutoModelForCausalLM` になる
    - 生成の設定（`max_new_tokens` など）は引数にせず定数にする（呼ぶのは `answer` 関数だけ）
- `MAX_TOKENS` → **`MAX_NEW_TOKENS`** に改名：transformers の `max_length` は入力＋生成の合計、`max_new_tokens` は生成だけの上限。コンテキストだけで2000トークンを超えるので、`max_length=256` だと何も生成されない
- **`SmallLLMModel` の中身**（Claude が作成、2026-10-25。ユーザーが全部任せた）：
    - import を整理：`import torch`、`from transformers import AutoModelForCausalLM, AutoTokenizer, BatchEncoding`（標準ライブラリ → 外部 → 自分のパッケージの順）
    - `__init__`：cuda → mps → cpu の順に場所を選び、GPU は bfloat16、CPU は float32。`AutoTokenizer` と `AutoModelForCausalLM` で読み込み、`.to(device)`
    - `generate`：`apply_chat_template(messages, add_generation_prompt=True, enable_thinking=False, return_tensors="pt", return_dict=True)` → `assert isinstance(inputs, BatchEncoding)`（型の絞り込み）→ `.to(self.model.device)` → `self.model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False)` → 入力の分を切り落とし（`generate` は入力も含めて返す）→ `batch_decode(..., skip_special_tokens=True)[0].strip()`
    - 型ヒント：`AutoModelForCausalLM` で読み込むと、破棄した実装で出た `generate` のエラーは出なかった。残る `.to(device)` だけ、理由を書いて `# type: ignore[arg-type]`
    - `enable_thinking` はテンプレートに渡す変数なので、Qwen3 以外のモデルでは無視される
    - 試した結果（mps）：読み込み10.3秒（ほかの処理と重なった可能性あり。前回は約4〜5秒）。「What is 2 + 3?」→ `'2 + 3 = 5.'`（4.5秒）、「Say hello.」→ `'Hello! How can I assist you today?'`。警告は出なかった
- メソッド名：`self.model.generate` と重なるので一度 `gen` にしたが、LLM の言葉として `generate` 以上のものがないので **`generate` に戻した**（ユーザー）。持ち主が違うので別物として動く
- VS Code（Pylance）だけが `self.model.generate` に「`_BaseModelWithGenerate` は `GenerativePreTrainedModel` を満たさない」と出す。transformers の型ヒントの癖で、実行と mypy には影響なし → **放っておく**（ユーザー）。黙らせるなら `# pyright: ignore[reportAttributeAccessIssue]`（`# type: ignore` は mypy の `--warn-unused-ignores` で落ちる）
- 読解（2026-10-26〜27）：
    - **Qwen を使う手続き**：①ライブラリ（PyTorch、transformers）②Hugging Face Hub からファイルを取得（初回の `from_pretrained` で自動。`~/.cache/huggingface/hub/`。ログイン不要）③tokenizer とモデルを読み込む（精度とデバイスを決める）④使う（メッセージ → テンプレート → 番号 → 生成 → 文章）
    - ダウンロードされたファイル：`model.safetensors`（重み、1.4GB）、`config.json`（形。`model_type: qwen3`、`architectures: Qwen3ForCausalLM`）、`generation_config.json`（生成の既定値）、`vocab.json`・`merges.txt`・`tokenizer.json`（語彙表と分け方）、`tokenizer_config.json`（チャットのテンプレート）
    - **Qwen というライブラリは import しない**。設計図（コード）は transformers の中（`transformers/models/qwen3/modeling_qwen3.py`）、中身（重み・設定・語彙）は Hub。`Auto` のクラスが `config.json` を見て設計図を選ぶ
    - GitHub の QwenLM/Qwen は Qwen 1（2023）のリポジトリで、更新停止。デモ、追加学習、量子化、評価、技術レポートなど。設計図のコードはない（当時は Hub に置いて `trust_remote_code=True`）。Qwen3 は QwenLM/Qwen3 で、こちらも設計図はなく、transformers（4.51.0 以上）で読み込むよう案内（GitHub の README で確認）
    - **transformers**：Hugging Face の、学習済みモデルを読み込んで使うライブラリ。設計図、読み込み（`from_pretrained`）、tokenizer（テンプレート）、生成（`generate`）。PyTorch の上に乗る（transformers = 組み立てと使い方、PyTorch = 実際の計算）
    - **`__init__` の条件分岐**：「レイヤー」ではなく**デバイス**（計算装置）と**精度**を決めている。cuda（NVIDIA の GPU）→ mps（Apple Silicon の GPU、Metal）→ cpu の速い順。GPU は bfloat16、CPU は float32（CPU の bfloat16 は遅い）。重みは16ビットで約1.2GB、32ビットで約2.4GB。モデルと入力は同じデバイスにないと計算できないので、`generate` で `inputs.to(self.model.device)`
- **デバイスの選び方の議論**（2026-10-27）：
    - cuda と mps はどちらも GPU だが、メーカーと動かす仕組みが違う（NVIDIA の CUDA、Apple の Metal）。PyTorch は GPU ごとに別の計算プログラムを持つ。両方が1台にあることはまずないので、cuda と mps の順番に速さの意味はない（「速い順」は不正確だった）
    - ほかの GPU：AMD は ROCm 版の PyTorch で `cuda` の名前のまま動く。Intel は `xpu`（今の torch に `torch.xpu` があることを確認）。TPU は `xla`（別パッケージ）
    - 今の torch（2.14.1）には `torch.accelerator.current_accelerator()` がある（この Mac では `mps`）。メーカーを問わず GPU を返す。ただし**既定の `check_available=False` だと「ビルド時点で対応している GPU」を返し、実際に使えるかは見ない** → `check_available=True` が必要（ソースの docstring で確認）。書き換えるかは未決
    - ビルド：ソースをコンパイルしてパッケージにする作業。開発元がビルド済みのものを配っている。**uv は OS・CPU の種類・Python の版でパッケージを選び、GPU は見ない**（`uv.lock` の marker は `platform_machine` だけ）。Linux 用の torch は NVIDIA の GPU 用のビルドで、GPU のない普通の Linux マシンにも入る
    - 精度：重みは小数なので浮動小数点数。bfloat16 は Google Brain の16ビット形式（範囲は float32 と同じ、細かさを削る）。GPU には16ビット用の専用回路があり速い。CPU には少ないので遅い。`dtype` を指定しないと `config.json` の `"torch_dtype": "bfloat16"` が使われる（実際に試して bfloat16）→ 指定が効くのは CPU（float32）のときだけ
    - `from_pretrained`：クラスから呼ぶメソッド。Hub（2回目からはキャッシュ）からファイルを読み、オブジェクトを組み立てる。モデルに tokenizer は入っていない（モデルは番号しか扱わない）
    - `.to(device)`：重み（約6億個の数値そのもの）を、選んだ装置のメモリにコピーする。GPU は自分のメモリにあるデータしか計算に使えない。CPU なら何も起きない。「CPU 用のチューニング」ではない。この Mac は mps なので bfloat16（32ビットは GPU のないマシンだけ）
- **Linux では CPU 専用の torch を使う**（2026-10-27 ユーザーの決定）：
    - 理由：PyPI の Linux 用 torch は CUDA ビルドで、NVIDIA のライブラリを依存として持つ。`uv.lock` の記録で、Linux・x86_64 のダウンロードは NVIDIA 関連と triton で**約2.3GiB**（cudnn 527MiB、cublas 404MiB、triton 236MiB など）＋ torch 本体 529MiB。uv は GPU を見ないので、GPU がなくても入る
    - uv の公式ドキュメント（PyTorch の統合ガイド）で確認：PyPI は Linux に CUDA 13.0 のビルド、macOS と Windows に CPU ビルド。CPU 専用の配布場所 `https://download.pytorch.org/whl/cpu`。GPU を見て選ぶ `--torch-backend=auto` は `uv pip` だけで、`uv sync` とロックファイルには使えない
    - 「cpu」の名前でも macOS で mps が使える理由：Apple の GPU を動かす Metal は macOS に入っていて、ダウンロード不要。「cpu」版は「NVIDIA・AMD の GPU 用のライブラリを含まない」の意味と考えられる（推測）。CPU 用の配布場所の macOS 用ファイルは `+cpu` の印がなく、PyPI と同じ名前
    - 実装：`pyproject.toml` に `[tool.uv.sources]`（`torch = [{ index = "pytorch-cpu", marker = "sys_platform == 'linux'" }]`）と `[[tool.uv.index]]`（`explicit = true`）を追加。理由を英語のコメントで書いた。**Linux だけに限定**し、Mac は PyPI のまま（mps を確実に残すため）
    - 結果：`uv lock` で `nvidia-*` と `triton` が消え、torch は `2.14.1`（PyPI、Linux 以外）と `2.14.1+cpu`（CPU 専用、Linux）の2つになった。`uv.lock` の `nvidia-` は0件。この Mac は `uv sync` 後も torch 2.14.1、`mps: True`
    - 代償：Linux に NVIDIA の GPU があっても使わず、CPU（float32）で動く
    - **残りのタスク**（ユーザーの指示、CLAUDE.md の進捗表にも記載）：審査の Linux マシン（校舎）に NVIDIA の GPU があるかを確かめ、CPU 専用のままでよいかを判断する。Linux での `uv sync` と answer の動作も確かめる
- **`__init__` の条件分岐を `torch.accelerator` に書き換えた**（2026-10-27 ユーザーの決定）：
    ```python
    device = torch.accelerator.current_accelerator(check_available=True)
    dtype = torch.bfloat16
    if device is None:
        device, dtype = torch.device("cpu"), torch.float32
    ```
    - `check_available=True` が要る理由をコメントに書いた（ないと、GPU のないマシンでもビルド時点の GPU を返す）。docstring も「マシンの GPU（CUDA、MPS など）が今使えればそれ、なければ CPU」に直した
    - `device` は文字列ではなく `torch.device` になった（`.to()` はどちらも受け付ける）
    - 試した結果（この Mac）：`mps:0`、`torch.bfloat16`。「What is 2 + 3?」→ `'2 + 3 equals 5.'`。flake8 通過、mypy の `answer.py` のエラーは `answer_dataset` の仮のコードの1件だけ（`.to` の `# type: ignore` は引き続き必要だった）
- 読解（2026-10-27 続き）：
    - `from_pretrained`：クラスメソッド。名前からファイルを用意（キャッシュかダウンロード）し、組み立てて返す。モデルは `config.json` の `model_type` で設計図を選び、空のモデルに重みを `dtype` に変換してはめ込む
    - tokenizer は文章 ↔ 番号の両方向（BPE の結合の規則 `merges.txt` で切り分け、`vocab.json` で番号に）とテンプレート。モデルは番号の列から「次のトークンの確率」を出すだけで、繰り返して文章にするのは `generate`。Causal LM は「前のトークンだけを見て次を予測する」モデル
    - 語彙表は `__init__` の `from_pretrained` の時点でメモリに入る（`Qwen2Tokenizer`、151,669個。`"vLLM supports LoRA adapters"` → `['v', 'LL', 'M', 'Ġsupports', 'ĠLo', 'RA', 'Ġadapters']`、`Ġ` は前の空白）
    - 重み = 学習で決まった数値（パラメータ）だけ。学習データ（文章）は入っていない。総数 596,049,920個（0.6B）。例：`model.embed_tokens.weight (151936, 1024)`（トークン1つにつき1行）、`layers.0.self_attn.q_proj.weight (2048, 1024)`
    - `.to(device)`：重みを計算装置のメモリにコピーし、CPU 側のコピーは捨てられる（2倍のままにはならない）。実測：from_pretrained 後 CPU 911MiB・MPS 0 → `.to("mps")` 後 CPU 221MiB・MPS 1144MiB。`.to()` は同じオブジェクトを返す（`m.to(...) is m`）
    - `# type: ignore[arg-type]` は **`.to(device)` の行**のため（`generate` ではない）。transformers が `.to` をデコレータで包んでいて、型ヒントでは1つ目の引数が `PreTrainedModel` に見える。`[arg-type]` で引数の型のエラーだけを黙らせる
- **`generate` の読解**（2026-10-27〜28）：
    - `apply_chat_template`：メッセージをテンプレートで1本の文字列に整え（`<|im_start|>role\n...<|im_end|>`）、番号に変えるだけ。返答は作らない。この時点でモデルの計算はしない（tokenizer だけ）。チャットの形にしてもモデルがやるのは「続きの予測」で、違うのは学習で見慣れた形かどうか
    - 引数：`add_generation_prompt=True`（最後に `<|im_start|>assistant\n`）、`enable_thinking=False`（空の `<think>\n\n</think>\n\n` を入れる。テンプレート側の責任）、`return_tensors="pt"`（PyTorch のテンソル）、`return_dict=True`（`input_ids` と `attention_mask` の `BatchEncoding`。**この版では既定値が True**なので書かなくても同じ。学習のため明示したまま残す、とユーザーが判断）
    - `tokenize=False` ならテンプレートで整えた文字列（`str`）で止まる（切り分けも番号化もしない。`Ġ` は切り分けたトークンを文字列で見たときだけの表記）。複数の会話なら `list[str]`
    - `attention_mask`：本物のトークン（1）か、長さをそろえる詰め物（0）か。特別なトークンも改行も本物（1）。詰め物は長さの違う複数の入力を1つのテンソルにまとめるときだけ（numpy と同じく長方形でないとまとめて計算できない）。今は1件ずつなのですべて1。`return_dict=False` でも同じ答え・警告なしだったが、学習のため attention_mask を明示する形のままにした（ユーザー）
    - `BatchEncoding`：今回の中身は `input_ids` と `attention_mask` だけ。tokenizer のオプションで `token_type_ids`、`special_tokens_mask`、`offset_mapping`（各トークンの元の文字の範囲）、`length` も入る。`dict` の子クラスではなく `UserDict` が土台。`__getitem__`（`inputs["input_ids"]`）と `__getattr__`（`inputs.input_ids`）の両方を自分で用意している。メソッド `to`、`tokens`、`word_ids` など。普通のクラスや pydantic のモデルは `obj["x"]` できない（`TypeError: not subscriptable`）
    - `assert isinstance(inputs, BatchEncoding)`：成功の確認ではなく、**mypy への型の絞り込み**（戻り値の型ヒントが `str | list[int] | list[str] | list[list[int]] | BatchEncoding`）。失敗なら `apply_chat_template` の時点で例外。`assert` は前提の確認で、`-O` で消えるので外からの入力の検証には使わない。`typing.cast` は実行時に確かめない
    - `inputs.to(self._model.device)`：入力のテンソルを GPU のメモリにコピー（`BatchEncoding.to` は中の値を1つずつ `.to` して `self` を返す）。`self._model.device` は保存した値ではなくプロパティ（`next(param.device for param in self.parameters())`）。`.to()` は**その行で実際にコピーする**（予約ではない。GPU への命令は非同期のことがあるが順番は崩れない）。モデルの `.to()` は副作用あり（同じオブジェクトの重みを差し替える）
    - `self._model.generate(**inputs, ...)`：`**` は二重展開ではなく、辞書をキーワード引数に展開する記号（`input_ids=...`、`attention_mask=...`）。戻り値は入力＋生成をつなげた番号のテンソル `(件数, 入力長＋生成長)`
    - `do_sample=False`：一番確率の高いトークンを選ぶ（貪欲法、毎回同じ答え）。`True` は確率に従ったくじ引き（Qwen3 の既定は True、temperature 0.6、top_k 20、top_p 0.95）
    - `output[:, inputs["input_ids"].shape[1]:]`：全行・入力の長さ以降の列＝生成した部分だけ。実例：入力15個 → 出力25個 → 生成10個 `[9707, 0, 2585, ..., 151645]`。`batch_decode` は2次元（番号の列の集まり）を受け取り文字列のリストを返す。`skip_special_tokens=True` で末尾の `<|im_end|>`（151645）を除く。`[0]` で1件目、`.strip()` で前後の空白
    - `inputs["input_ids"].shape`：テンソルの形の属性（`torch.Size([1, 15])` = 1件 × 15トークン）。`shape[1]` が入力の長さ。1件でも `(1, 長さ)` の2次元
    - なぜ `BatchEncoding` は辞書の形か（推測）：項目がモデルやオプションで変わる、キー名がモデルの引数名と同じで `**inputs` で渡せる。属性の書き方（`__getattr__`）は mypy で `Any`、打ち間違いも見つからない。**辞書の書き方も、実際のコードでは `Any`**（`apply_chat_template` の戻り値が値の型を指定しない `BatchEncoding` なので、`Generic[_V]` の `_V` が既定の `Any`）。`BatchEncoding[Tensor]` と明示したときだけ `__getitem__` の `@overload` で `Tensor` になる。一度「辞書なら型が分かる」と説明したのは、明示した型で試した誤り → 訂正済み。辞書の書き方にしている理由は、transformers の使用例と同じ、`**inputs` と見方がそろう、の2つだけ
    - `skip_special_tokens=True`：文章に戻すときに特別なトークンを除く。生成した部分の最後には必ず `<|im_end|>`（151645）が付くので、それを答えから消している
    - `reply[0].strip()`：`batch_decode` は入力した行の数だけ文字列を並べたリストを返す（メタデータは入らない）。1件なので要素は1つ。`.strip()` は前後の空白・改行を除く念のための後始末（これまでの答えではもともと付いていなかった）。前後の改行はモデルの学習の癖（判断ではない。外から制限をかける constrained decoding とは別物）
    - `batch_decode` の第一引数は**番号**：`list[int] | list[list[int]] | np.ndarray | torch.Tensor`、戻り値 `list[str]`。今回は整数（int64）のテンソル `(1, 生成長)`。`Tensor[str]` という型はない（中身の型は `dtype`）
    - docstring："This method is provided for backwards compatibility. The `decode` method now handles batched input natively"。`decode` の戻り値は `str | list[str]` で mypy の絞り込みが要るので、`batch_decode` を使い続ける。**将来の版で `batch_decode` がなくなる可能性**に注意
    - 入力の長さの別の書き方：`inputs.input_ids.shape[1]`、`.shape[-1]`、`.size(1)`、`len(...[0])`。どれも同じ。読みやすくするため `prompt_length = inputs["input_ids"].shape[1]` に分けた（2026-10-28 ユーザーの決定）
- **`answer` 関数**（2026-10-28、案で合意して Claude が作成）：
    - A. コンテキスト：`[i] <file_path>\n<本文>` を空行でつなぐ（番号は出典を示させるため、パスはドキュメントかコードかの手がかり）
    - B. メッセージ：system に `SYSTEM_PROMPT`、user に `"Context:\n{context}\n\nQuestion: {question}"`
    - C. `SYSTEM_PROMPT`：破棄した実装と同じ文（vLLM についての質問に、番号付きの抜粋だけで答える。なければそう言う。数文で、`[1]` のように出典を示す）。後で比べながら直す前提
    - D. 渡されたヒットは全部使う（件数を絞るかは `answer_dataset` で決める）
    - 結果（mps、`search --k 5` 相当）：LoRA の質問 5.5秒、答えは破棄した実装と同じ（`VLLM_ALLOW_RUNTIME_LORA_UPDATING` と LoRAResolver の話。5件中4件が `lora.md`）。フランスの首都 1.8秒、「Paris, as indicated in the example provided in the context. [1]」→ **関係のない質問を断れていない**（プロンプトの課題が残る）
    - flake8 通過。mypy の残りは `answer_dataset` の仮のコードと `Orchestrator.answer` の `-> None`
- **`answer` コマンドの完成**（2026-10-28）：`Orchestrator.answer` の `-> None` と `SmallLLMModel()` を渡す部分はユーザーが作成済み。表示を Claude が作成：答えの文章 → 空行 → 使ったヒットを `[i] <file_path> [first:last]` で1行ずつ（答えの中の `[1]` と対応させるため番号付き。`search` コマンドと同じ形に番号を足した）。数字だけのクエリのコメントも付けた
    - 実行例（mps）：LoRA の質問 `--k 5` でコマンド全体13.1秒（import、モデルの読み込み約4秒、生成約5秒）。transformers が `Loading weights` の進捗バーを標準エラー出力に出す
    - `answer 123 --k 2`：「The context provided does not contain the answer to the question. [1] is the context excerpt given.」→ 意味のない質問は断れた
    - 気づき：LoRA の質問のヒット [2] は `lora.md [0:1874]`（文書の冒頭。LoRA の使い方の説明があるはず）なのに、答えは [1]〜の `VLLM_ALLOW_RUNTIME_LORA_UPDATING` を選んでいる → プロンプトや thinking の比較で見直す
- **`answer_dataset`**（2026-10-28、ユーザーの指示で Claude が作成。search と search_dataset の関係と同じ形）：
    - `answer.py` の `answer_dataset(student_search_results_path, save_directory) -> Path`：`StudentSearchResults.model_validate_json` で読む → `SmallLLMModel()` を**1回だけ**作る → `tqdm(desc="Answering")` で全問に `answer` → `StudentSearchResultsAndAnswer`（`k` は入力ファイルの `k` を引き継ぐ）→ `save_directory/<入力と同じファイル名>` に `indent=2` で書き、パスを返す
    - `Orchestrator.answer_dataset`：`-> None`、`Saved student_search_results_and_answer to <path>`（課題の例と同じ文言）。課題の例の `Loaded 100 questions ... Processed 100 of 100 questions` の行は、tqdm の進捗バーで代わりにしている（文言は合わせていない）
    - ヒットは**全部使う**（`search_dataset --k 10` なら10件）。決定 D のとおり、絞るかは後で
    - 試した結果（docs の最初の3問、`--k 10` のラン、mps）：1問あたり約5.5秒、コマンド全体32秒 → **100問なら約9〜10分**の見込み。3問とも質問に沿った答え（`/v1/load_lora_adapter`、`lm_eval --model vllm`、`embed` メソッド）。出力の項目は `question_id`、`question`、`retrieved_sources`、`answer`、`k=10`
    - flake8、**mypy ともにエラーなし**（answer の仮のコードがなくなり、全ファイルで初めて mypy が通った）
- **`answer_dataset` を docs の全100問で実行**（2026-10-28、mps、`--k 10` のラン）：
    - 出力：`data/output/search_results_and_answer/UnansweredQuestions/dataset_docs_public.json`。終了コード0
    - 時間：コマンド全体 1276秒（約21分）。**途中で Mac がスリープしたので、実際の計算時間はもっと短い**（3問で1問約5.5秒だったので、計算だけなら約10分の見込み）。実行中の RSS が 83MB と小さかったのは、スリープ前後のメモリの圧縮・追い出しの可能性（推測）
    - 答えの様子：100問すべて答えあり（空は0）。長さは 67〜882文字（中央値277）。256トークンで打ち切られたと思われる長い答えは0。同じ文の繰り返し（3回超）は0。「コンテキストに答えがない」と答えたのは1問
    - 例：「What hardware platforms does vLLM support?」→ NVIDIA GPUs, Intel GPUs, Apple silicon, CPUs …。「Where can I find information about using generative models?」→ リンクの文字列 `[generative_models.md](data/raw/vllm-0.10.1/docs/models/supported_models.md)` を自分で作っている（ファイル名とパスが食い違う）→ 幻覚の一種。プロンプトの見直し候補
    - 答えの中身の正しさ（グラウンドトゥルースの `answer` との比較）はまだ見ていない
    - スリープ対策：`caffeinate -i`（Ctrl+C か `killall caffeinate` で止める。どのディレクトリでも動く）。`caffeinate -i <コマンド>` ならコマンドの間だけ（プロジェクトの直下で実行）
- **幻覚（リンクの混ぜ合わせ）の調査と対応**（2026-10-28）：
    - 例：「Where can I find information about using generative models?」→ `[generative_models.md](data/raw/vllm-0.10.1/docs/models/supported_models.md)`。コンテキスト [1] の見出し（こちらが付けたパス `supported_models.md`）と、本文の相対リンク `See [this page](generative_models.md)` を混ぜて1つのリンクにした。作り話ではなく本物の情報2つの誤った組み合わせ。**コードのバグではない**（決めたとおり渡している）
    - 原因の候補：こちらが付けたパスの見出し、ドキュメントの相対リンク（基準がモデルに分からない）、プロンプトがパスやリンクを禁じていない、0.6B の限界。RAG の考え方が壊れたわけではない（課題も "mostly grounded" でよいとしている）が、具体的で間違った答えは誤解を招く
    - docs 100問のうち、Markdown のリンクを書いた答え9、パスやファイル名を書いた答え11、`[n]` で出典を示した答え50
    - 11問で比較：プロンプトに「リンクやパスを書かない」を足すだけ → 9/11 が残る（ほぼ効かない）。＋見出しからパスを外す（`[i]` と本文）→ 2/11、`data/raw` は0 → **パスの見出しが主な原因**と確認。小さいモデルは指示より目の前の文字列を写す傾向が強い
    - **決定（ユーザー）：コンテキストは本文だけ**（番号も外す。番号を残す案 A より単純さを選んだ）。`SYSTEM_PROMPT` から番号の出典指示を外し、「リンクやパスを書かない」は残した：`"You answer questions about the vLLM codebase. Use only the context given by the user. If it does not contain the answer, say that the context does not contain it. Answer in a few sentences; do not write links or file paths."`。docstring に理由を書いた
    - 結果（14問：11問＋最初の3問）：パスやリンクは 2/14。`data/raw` は0。ただし残った2問は、**本文の相対リンクから URL を作っている**（`https://docs.vllm.ai/en/latest/generative_models.md`：作った URL。`../examples/online_serving/structured_outputs.md`：本文の相対リンクを写した可能性）→ 見出しが原因の分は消えたが、本文由来のリンクの幻覚は残る
    - 答えは全体に短くなった（例：`VllmConfig` の答えから `vllm/config.py` が消えた）。フランスの首都は「The capital of France is Paris.」（断れない問題は残る。前は「as indicated in the example」と資料を根拠にしていた）
    - `answer` コマンドの表示の番号 `[i]` は、答えの中の番号と対応しなくなった（見直し候補）
- **`answer` コマンドの表示の変更**（2026-10-28、ユーザーが作成）：既定は答えの文章だけ。`--show_retrieved_sources` を付けたときだけ、ヒットを `<file_path> [first:last]` で並べる（番号なし。プロンプトで番号を使わなくなったため）。答えの前に空行。docstring は Claude が直した（"Print the answer to a single query. With show_retrieved_sources, also print the sources it was based on."）
    - 条件はユーザーが `if show_retrieved_sources:` にした。Fire は小文字の `true`/`false` や `yes` を**文字列**で渡すので、`--show_retrieved_sources=false` でも表示される（`is True` なら本物の True だけ）。普段の使い方（値なしの `--show_retrieved_sources`、`True`/`False`）では問題なし
    - **Fire は型ヒントを見ない**（`fire/parser.py` の `DefaultParseValue`：`ast.literal_eval` で Python の値として読めればその値、読めなければ文字列）。`True` → bool、`true` → 文字列、`5` → int、`abc` → 文字列。型の確認はエラー処理の段階でこちらが行う
- **クラスの属性に `_` を付けた**（2026-10-27 ユーザーの指示、慣習的なカプセル化）：`self.tokenizer` → `self._tokenizer`、`self.model` → `self._model`。ほかのファイルからの参照はなし。flake8 通過、動作確認（`mps:0`、`'Hello! How can I assist you today?'`）
- `MinimalAnswer` の作り方：`MinimalAnswer` は `MinimalSearchResults` を継承していて項目が平ら。`MinimalAnswer(**retrieved.model_dump(), answer=res)` か、3つの項目を1つずつ書く

### 破棄した実装の記録（コアの部分、2026-10-25）

| ファイル | 中身 |
|---|---|
| `src/answer.py`（新規） | `load_model()`：動かす場所を cuda → mps → cpu の順に選ぶ（GPU は bfloat16、CPU は float32）。`read_source(source)`：`data/raw/` のファイルを index と同じ読み方（`read_text(encoding="utf-8")`）で読み、`text[first:last]` を返す。`answer(result, tokenizer, model) -> MinimalAnswer`：番号付きの資料（`[1] <file_path>\n<本文>`）と質問をチャットのテンプレートで渡し、thinking なし・貪欲法・`max_new_tokens=256` で生成。ID・質問・位置は `result` からそのまま写す |

- 定数：`MODEL_NAME = "Qwen/Qwen3-0.6B"`、`MAX_NEW_TOKENS = 256`、`SYSTEM_PROMPT`（vLLM についての質問に、番号付きの資料だけを使って答える。資料に答えがなければそう言う。数文で答え、使った資料を `[1]` のように番号で示す）
- 設計：search と同じく関数で作る（search Q8）。ただし**モデルは `load_model()` で1回だけ読み、`answer` に渡す**（読み込みに約4〜5秒かかり、100問で毎回読むと7分以上の無駄になるため。search の索引は17ミリ秒だったので毎回読んでいた）
- 型ヒント：`AutoModelForCausalLM` は `generate` を持たない型として扱われるため、`Qwen3ForCausalLM` を直接使う。transformers の型ヒントの癖で2か所に `# type: ignore` を付けた（`.to(device)` と `generate`）。`device_map` で `.to` を避ける方法は `accelerate` が必要なので採らない（実際に試して `ValueError`）
- `apply_chat_template` の戻り値は型の上では union なので、`assert isinstance(inputs, BatchEncoding)` で絞る。`decode` も union を返すので `batch_decode(...)[0]` を使う
- 生成の既定値（`GenerationConfig`）はサンプリングあり（`do_sample=True`、temperature 0.6、top_k 20、top_p 0.95）。毎回同じ答えにするため `do_sample=False` を指定。文脈の長さは `max_position_embeddings = 40960`
- 試した結果（mps）：モデルの読み込み 5.1秒。LoRA の質問は10.9秒、「What is the capital of France?」は4.6秒
    - LoRA：前と同じく `VLLM_ALLOW_RUNTIME_LORA_UPDATING` の話＋LoRAResolver のプラグイン。5件中4件が `lora.md` なのに、素直な答え（LoRA を有効にする方法）になっていない可能性
    - フランスの首都：「Paris, as indicated in the example provided in the context. [1]」。資料（テストのファイル）にたまたま Paris が出てくるのを根拠にしている。vLLM と無関係な質問を断れていない → プロンプトの課題
- flake8 通過。mypy のエラーは中身が空の `answer_dataset` などの2件だけ

### 決めたこと

- ライブラリは **transformers と PyTorch**（2026-10-24 ユーザーの決定）。torch 2.14.1、transformers 5.20.2（Q3）
- 流れは「案A の修正版」：チャットのテンプレート、thinking なし、EOS か `max_new_tokens` で止める、ID・位置・k はこちらのコードで入れる（Q2）

### 引き継いだもの

- `answer_dataset` の入力は `StudentSearchResults`（位置だけで本文がない）。本文は `data/raw/` のファイルから `text[first:last]` で取り出す（search Q6）
    - index と同じ読み方（`encoding="utf-8"`）をしないと位置がずれる。CRLF の問題も関わる（index の既知の問題）
- `answer` は1問を `search`（`UnansweredQuestion` を渡す。search Q8）してから答える
- 検索は意味を扱わない（`not` を捨てる）。意味を読むのは Qwen の役目（evaluate Q2）
- 正解データを answer で使うのはカンニング（search Q2）

### この PC（2026-10-24 に確認）

- Apple M3（CPU 8コア：高性能4＋高効率4）、GPU 10コア（Metal 4。PyTorch では `mps`）
- メモリ 8GB（CPU と GPU で共有）。確認時は空き約90MB、圧縮 2.9GB で詰まっていた
- ディスクの空き 98GB

### 未決事項

- ~~本文の取り出し方~~ → `read_source`（済み）
- ~~動かす場所と精度~~ → `torch.accelerator`、GPU は bfloat16、CPU は float32（済み）
- ~~モデルの読み込みを1回で済ませる作り~~ → 案A：`answer(retrieved, llm)` に `SmallLLMModel` を渡す（済み）
- プロンプトの組み立て（`SYSTEM_PROMPT`、コンテキストの並べ方、出典の示し方）
- トークンの予算（チャンクを何件・何トークンまで入れるか）
- **Qwen3 の thinking を使うか**（2026-10-27 タスクに追加、ユーザーの指示）：今は `enable_thinking=False`。LLM は黙って考えられず、思考は `<think>`〜`</think>` の文章を実際に生成すること。「思考させて、過程は出力しない」は、全部生成してから `</think>`（id 151668）より前を捨てれば実現できる。`False` にした理由（破棄した実装で Claude が選んだもの）：時間（思考は数百〜数千トークン）、`max_new_tokens=256` で答えの前に打ち切られる危険、後処理が要る。ただし思考で答えの質が上がる可能性（複数のコンテキストの見比べ）はある → **同じ質問いくつかで、思考あり／なしの答えと時間を比べて決める**。思考ありにするなら `max_new_tokens` も見直す
    - **thinking を使うときの懸念点**（2026-10-27 ユーザーの指示で記録）：
        1. **時間**：思考は数百〜数千トークン。mps でも1秒に数〜十数トークンだったので、1問あたり数十秒〜数分。審査の Linux は CPU 専用の torch（float32）なので、さらに遅い。answer に時間制限はないが、100問の `answer_dataset` が現実的な時間で終わるか
        2. **打ち切り**：思考が `max_new_tokens` を超えると、`</think>` の前で止まり、**答えが空**になる。`max_new_tokens` を大きくすると、1の時間がさらに伸びる
        3. **後処理**：`</think>` より後だけを取り出す処理が要る。`</think>` が出ないまま止まった場合（2）の扱いも決める必要がある（空にする、思考をそのまま使う、もう一度生成する など）
        4. **貪欲法との相性**：思考は長いので、貪欲法（`do_sample=False`）だと同じ文の繰り返しに陥りやすい可能性。サンプリングにすると、答えが毎回変わり、比べにくくなる（Qwen の推奨設定は未確認）
        5. **メモリ**：生成が長いほど、途中の計算の記録（KV キャッシュ）が増える。メモリ 8GB のこの Mac で、長い入力（コンテキスト2000トークン超）＋長い思考に耐えられるか（未確認）
        6. **質が上がる保証はない**：0.6B の思考は、長いわりに的外れなこともある。思考の中でコンテキストにない話を作り、それを答えに持ち込む（幻覚）おそれも
        8. **`skip_special_tokens=True` では `<think>` が消えない**（2026-10-28 確認）：tokenizer の特別なトークン（14個：`<|im_end|>`、`<|endoftext|>`、`<|im_start|>` など）に `<think>`/`</think>` は入っていない。思考を捨てるには `</think>`（id 151668）の位置で切り分ける必要がある
        7. **評価で見えない**：思考を捨てるので、レビュアーには答えしか見えない。思考の手間が答えに表れなければ、時間をかけた意味がない
        - 比べるときは、答えの質（grounding、質問に答えているか）、時間、生成したトークン数、答えが空になった件数を記録する
- 生成の設定：`max_new_tokens`（256 でよいか）、貪欲法（`do_sample=False`）で繰り返しが起きないか
- `answer` コマンドの出力の形
- `answer_dataset` の `k`（入力ファイルの `k` を引き継ぐか、ヒットを何件使うか）

---

## 1. 質問ごとのまとめ

### Q1. answer の k の意味

- `answer <query> --k`：`search` で上位 k 件のチャンクを持ってきて、その本文を Qwen に渡して答えさせる
- k は大きければよいとは限らない：答えが含まれる可能性は上がるが、雑音も増え、小さいモデルは引っ張られやすい（課題："search too much and you drown the model in noise"）。トークンの予算にも限りがある
- `answer_dataset` には k の引数がない。チャンクの数は入力ファイルの `retrieved_sources`（`search_dataset --k 10` なら10件）で決まる。全部渡すか上位の数件にするかは未決
- 出力の `k` は「検索で何件取ってきたか」なので、入力ファイルの `k` を引き継ぐのが自然

### Q2. answer の内部処理の流れ（案A と案B）

- ユーザーの案：プロンプト `query: <query>` に `search` の結果を足し、
    - 案A：`answer: ` の続きを、指定のトークン数かピリオドまで生成し、その部分を答えにする
    - 案B：search の結果を JSON にし、答えも JSON の続きとして constrained decoding で作る
- 共通の修正：`search` の結果は位置だけ。**本文を `data/raw/` から取り出して渡す**。`input_ids` はトークンの番号の列（文字列を tokenizer で変換したもの）
- **案B は採らない**：課題の "produce structured JSON following the provided pydantic models" は出力ファイルの形のことで、ID・位置・k はこちらのコードが pydantic で作れる。モデルに作らせるのは `answer` の文章だけでよい。JSON ごと書かせると写し間違いの危険、追加の仕組み、小さいモデルの質の低下がある（call_me_maybe は関数呼び出しの形そのものが出力だったので必要だった）
- **案A を修正して採る**（2026-10-25 ユーザーの了承）：
    1. ピリオドで止めない（最初の文で止まる、`3.5` や `vllm.LLM` でも止まる）。**EOS で止め、`max_new_tokens` で打ち切る**
    2. `query:`/`answer:` ではなく、**チャットのテンプレート**（`apply_chat_template`）で system（指示）と user（資料と質問）を渡す。grounding とプロンプトの工夫は主に system に出る
    3. Qwen3 の thinking モードは使わない
- 流れ：
    ```
    質問 → search（上位 k 件の位置）→ data/raw/ から本文を取り出す
         → チャットのテンプレートでプロンプト → tokenizer → input_ids
         → generate（EOS か max_new_tokens で止まる）→ 生成部分だけを文字列に戻す = answer
         → MinimalAnswer（ID と位置はこちらのコードで入れる）
    ```

### Q3. transformers と PyTorch を入れ、Qwen3-0.6B を試す（2026-10-25）

- `uv add transformers torch` → **torch 2.14.1、transformers 5.20.2**（`pyproject.toml` は下限だけ、正確な版は `uv.lock`）。`torch.backends.mps.is_available()` は True
- チャットのテンプレート（実物で確認）：
    - 形式は `<|im_start|>system\n...<|im_end|>\n<|im_start|>user\n...<|im_end|>\n<|im_start|>assistant\n`
    - `enable_thinking=False` にすると、assistant の後に**空の `<think>\n\n</think>\n\n`** が入り、考えの部分を飛ばして答えから始まる。`True`（既定）では何も入らず、モデルが考えを書き出す
    - EOS は `<|im_end|>`（id 151645）。pad は `<|endoftext|>`
- 試したこと（scratchpad の `try_qwen.py`）：質問「How do I enable LoRA adapters when serving a model with vLLM?」、上位5件のチャンク（8375文字）、`enable_thinking=False`、`max_new_tokens=256`、`do_sample=False`（貪欲法）

| 場所 | dtype | 読み込み | 入力 | 出力 | 生成時間 | 最大メモリ（RSS） |
|---|---|---|---|---|---|---|
| mps | bfloat16 | 3.9秒（初回はダウンロード込みで122秒） | 2260トークン | 52トークン | **8.0秒** | 0.93GiB |
| cpu | bfloat16 | 1.2秒 | 2260 | 53 | **161秒**（極端に遅い） | 1.61GiB |
| cpu | float32 | 5.2秒 | 2260 | 53 | **29.6秒** | 3.33GiB |

- 分かったこと：
    - **mps（GPU）が一番速い**。100問で約13分の見込み（1問約8秒）
    - **CPU で bfloat16 は使わない**（float32 の5倍以上遅い）。CPU なら float32
    - 時間の大半は、入力の2260トークンを読む部分と考えられる → 渡すチャンクを減らすと速くなる（未確認）
    - 審査の環境は Linux の可能性が高く、mps はない。**動かす場所を自動で選ぶ必要がある**（例：cuda → mps → cpu）
    - モデルのキャッシュは `~/.cache/huggingface/hub/models--Qwen--Qwen3-0.6B`（`du -shL` で 2.8G。シンボリックリンクの二重計上を含む可能性あり）
- 答えの中身：「`VLLM_ALLOW_RUNTIME_LORA_UPDATING` を `True` にする」。資料の中にある記述だが、これは**実行中に LoRA を差し替える機能**の話で、質問への一番素直な答え（LoRA を有効にする方法）とはずれている可能性が高い（正解は未確認）→ プロンプトや渡すチャンクの工夫が要る

---

## 2. 答え合わせしていない確認の質問

（ここから追記）

## 3. 次にやること

- ~~transformers と PyTorch を入れ、Qwen3-0.6B がこの PC で動くか確かめる~~（済み）
- `SmallLLMModel.generate` の読解の続き（`do_sample` まで済み。残り：入力の分を切り落とす処理、`batch_decode`）
- `answer` 関数（コンテキスト → メッセージ → `llm.generate` → `MinimalAnswer`）とプロンプト
- **thinking あり／なしの比較**（「0. 未決事項」）
- `Orchestrator.answer` の仕上げ、`answer_dataset`
- 校舎の Linux で：デバイスの確認と torch の指定の判断（CLAUDE.md の進捗表）

## 4. README に使えるポイント

（ここから追記）
