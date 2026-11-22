"""青空文庫テキストのクリーニングおよび文分割モジュール。"""

from __future__ import annotations

import re
from typing import List

# ヘッダ区切り線（ハイフン10個以上の行）
_HEADER_SEP_RE = re.compile(r"^-{10,}\s*$")
# ルビ: 《...》
_RUBY_RE = re.compile(r"《[^》]*》")
# 入力者注（外字記号 ※ を含む場合も除去）: ※［＃...］ または ［＃...］
_NOTE_RE = re.compile(r"※?［＃[^］]*］")
# 連続する空白の正規化（全角空白・半角空白・タブ）
_MULTI_SPACE_RE = re.compile(r"[ \t\u3000]+")

# 括弧の対応（会話文・引用文内の句点での不自然な分割を防ぐ）
_OPEN_BRACKETS = {"「": "」", "『": "』", "（": "）", "(": ")", "【": "】"}
_CLOSE_BRACKETS = set(_OPEN_BRACKETS.values())
_SENTENCE_ENDINGS = set("。！？!?")
# 意味のある文字（日本語・英数字）が1文字以上含まれるかの判定
_MEANINGFUL_CHAR_RE = re.compile(r"[ぁ-んァ-ヶ一-龥々〆ヵヶA-Za-z0-9０-９]")


def decode_aozora_bytes(raw_bytes: bytes) -> str:
    """青空文庫テキストのバイト列を文字列にデコードする（CP932優先）。"""
    for encoding in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    # フォールバック（置換文字で救済）
    return raw_bytes.decode("cp932", errors="replace")


def strip_header_footer(text: str) -> str:
    """青空文庫特有のヘッダ（記号説明枠）およびフッタ（底本情報以降）を除去する。"""
    # 改行コードをLFに統一
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    # 1. ヘッダの除去
    # 通常は2本のハイフン区切り線（---...---）の間に【テキスト中に現れる記号について】がある
    sep_indices = [i for i, line in enumerate(lines) if _HEADER_SEP_RE.match(line)]
    if len(sep_indices) >= 2:
        # 2本目の区切り線の直後から本文開始
        lines = lines[sep_indices[1] + 1 :]
    elif len(sep_indices) == 1:
        lines = lines[sep_indices[0] + 1 :]
    else:
        # 区切り線がないファイルの場合、先頭のタイトル・著者ブロック（最初の空行まで）をスキップ
        first_blank = next((i for i, line in enumerate(lines) if line.strip() == ""), None)
        if first_blank is not None and first_blank < 10:
            lines = lines[first_blank + 1 :]

    # 2. フッタの除去（末尾側から「底本：」行を探す）
    footer_idx = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("底本：") or stripped.startswith("底本:"):
            footer_idx = i
            break
    if footer_idx is not None:
        lines = lines[:footer_idx]

    return "\n".join(lines)


def clean_aozora_markup(text: str) -> str:
    """青空文庫のルビ・親文字記号・入力者注などのマークアップを除去する。"""
    # ルビ除去
    text = _RUBY_RE.sub("", text)
    # ルビの親文字指定記号を除去
    text = text.replace("｜", "")
    # 入力者注を除去（入れ子にも対応するため変化がなくなるまで適用）
    while True:
        new_text = _NOTE_RE.sub("", text)
        if new_text == text:
            break
        text = new_text
    # 残存する孤立した外字マーカーは極力影響を抑えつつ制御文字を削除
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def split_paragraph_into_sentences(paragraph: str) -> List[str]:
    """1段落を括弧のネストを考慮して文単位に分割する。"""
    sentences: List[str] = []
    buf: List[str] = []
    bracket_stack: List[str] = []
    n = len(paragraph)
    i = 0

    while i < n:
        ch = paragraph[i]
        buf.append(ch)

        if ch in _OPEN_BRACKETS:
            bracket_stack.append(_OPEN_BRACKETS[ch])
        elif ch in _CLOSE_BRACKETS:
            if bracket_stack and bracket_stack[-1] == ch:
                bracket_stack.pop()
            elif ch in bracket_stack:
                # 途中の括弧が閉じ忘れられていた場合の回復
                idx = len(bracket_stack) - 1 - bracket_stack[::-1].index(ch)
                bracket_stack = bracket_stack[:idx]

        # 括弧の外側で文末記号に到達した場合に文を区切る
        if not bracket_stack and ch in _SENTENCE_ENDINGS:
            # 連続する文末記号（例: ！？、。。）や直後の閉じ括弧を同じ文に含める
            while i + 1 < n and (
                paragraph[i + 1] in _SENTENCE_ENDINGS or paragraph[i + 1] in _CLOSE_BRACKETS
            ):
                i += 1
                buf.append(paragraph[i])
            sent = "".join(buf).strip()
            if sent and _MEANINGFUL_CHAR_RE.search(sent):
                sentences.append(sent)
            buf = []

        i += 1

    # 段落末尾の残余テキスト
    tail = "".join(buf).strip()
    if tail and _MEANINGFUL_CHAR_RE.search(tail):
        sentences.append(tail)

    return sentences


def extract_clean_sentences(raw_bytes: bytes) -> List[str]:
    """青空文庫の生バイト列からクリーンな1文単位のリストを返す。"""
    raw_text = decode_aozora_bytes(raw_bytes)
    body = strip_header_footer(raw_text)
    cleaned = clean_aozora_markup(body)

    sentences: List[str] = []
    for raw_line in cleaned.split("\n"):
        # 行頭・行末の空白（全角字下げ含む）を除去し、内部の連続空白を半角1つに正規化
        line = _MULTI_SPACE_RE.sub(" ", raw_line).strip()
        if not line:
            continue
        # 記号だけの装飾行（例: 「―――」「＊＊＊」「△　△　△」）は除外
        if not _MEANINGFUL_CHAR_RE.search(line):
            continue
        sentences.extend(split_paragraph_into_sentences(line))

    return sentences
