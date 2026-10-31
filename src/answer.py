import sys
from pathlib import Path

import torch
from tqdm import tqdm
from transformers import AutoModelForCausalLM, AutoTokenizer, BatchEncoding

from .data_models import (
    MinimalAnswer, MinimalSearchResults, MinimalSource, StudentSearchResults,
    StudentSearchResultsAndAnswer,
)

MODEL = "Qwen/Qwen3-0.6B"
MAX_NEW_TOKENS = 256
SYSTEM_PROMPT = (
    "You answer questions about the vLLM codebase. Use only the context "
    "given by the user. Answer in a few sentences."
)
NO_SOURCE_ANSWER = "No source in the corpus matches the question."
UNREADABLE_ANSWER = "None of the retrieved sources could be read."


def read_source(source: MinimalSource) -> str:
    """Return the text a source points to in its corpus file.

    Raise if the span goes past the end of the file.
    """
    # Read like build_index did, so the character indices line up.
    text = Path(source.file_path).read_text(encoding="utf-8")
    if source.last_character_index > len(text):
        raise ValueError(
            f"{source.file_path} has {len(text)} characters, fewer than "
            f"last_character_index {source.last_character_index}"
        )
    return text[source.first_character_index:source.last_character_index]


class SmallLLMModel:
    """Chat model that turns a list of messages into a reply text."""

    def __init__(self, model_name: str = MODEL) -> None:
        """Load the tokenizer and model on the best available device.

        Use the machine's GPU (CUDA, MPS, ...) if one can run now, else the
        CPU. GPUs run in bfloat16; the CPU runs in float32 because bfloat16
        is much slower there.
        """
        # Without check_available, this returns the GPU torch was built for
        # even when the machine has none.
        device = torch.accelerator.current_accelerator(check_available=True)
        dtype = torch.bfloat16
        if device is None:
            device, dtype = torch.device("cpu"), torch.float32
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_pretrained(model_name, dtype=dtype)
        # transformers' type hints for the wrapped .to() reject a device.
        self._model = model.to(device)  # type: ignore[arg-type]

    def generate(self, messages: list[dict[str, str]]) -> str:
        """Return the model's reply to messages, skipping Qwen3 thinking.

        Decoding is greedy, so the same messages give the same reply, and
        stops at the end-of-turn token or after MAX_NEW_TOKENS tokens.
        """
        inputs = self._tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, enable_thinking=False,
            return_tensors="pt", return_dict=True,
        )
        assert isinstance(inputs, BatchEncoding)
        inputs = inputs.to(self._model.device)
        output = self._model.generate(
            **inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False
        )
        # generate returns the prompt too; keep only the new tokens.
        prompt_length = inputs["input_ids"].shape[1]
        new_tokens = output[:, prompt_length:]
        reply = self._tokenizer.batch_decode(
            new_tokens, skip_special_tokens=True
        )
        return reply[0].strip()


def answer(
        retrieved: MinimalSearchResults, llm: SmallLLMModel
) -> MinimalAnswer:
    """Answer a question from the text of its retrieved sources.

    The context is only the source texts: with file paths in it, the model
    copied them into made-up links. A source that cannot be read is skipped
    with a warning. With no source, or none readable, the model is not
    called (it would make up an answer) and the answer is a fixed text. The
    question id, text and sources are copied from retrieved unchanged.
    """
    texts = []
    for source in retrieved.retrieved_sources:
        try:
            texts.append(read_source(source))
        except (OSError, ValueError) as e:
            tqdm.write(f"Warning: skipped a source of question "
                       f"{retrieved.question_id}: {e}", file=sys.stderr)
    if not retrieved.retrieved_sources:
        reply = NO_SOURCE_ANSWER
    elif not texts:
        reply = UNREADABLE_ANSWER
    else:
        context = "\n\n".join(texts)
        reply = llm.generate([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"Context:\n{context}\n\n"
                        f"Question: {retrieved.question}"},
        ])
    return MinimalAnswer(**retrieved.model_dump(), answer=reply)


def answer_dataset(
        student_search_results_path: str, save_directory: str
) -> Path:
    """Answer every question of a search results file and save them.

    Load the model once and answer each question from its retrieved
    sources. Write a StudentSearchResultsAndAnswer JSON file named after
    the input file under save_directory, creating the directory if needed.
    Return the path of the written file.
    """
    results = StudentSearchResults.model_validate_json(
        Path(student_search_results_path).read_bytes()
    )
    llm = SmallLLMModel()
    answers = StudentSearchResultsAndAnswer(
        search_results=[
            answer(r, llm)
            for r in tqdm(results.search_results, desc="Answering")
        ],
        k=results.k,
    )
    out = Path(save_directory)
    out.mkdir(parents=True, exist_ok=True)
    path = out / Path(student_search_results_path).name
    try:
        path.write_text(answers.model_dump_json(indent=2), encoding="utf-8")
    except BaseException:
        print(f"Warning: saving failed; {path} may be incomplete.",
              file=sys.stderr)
        raise
    return path
