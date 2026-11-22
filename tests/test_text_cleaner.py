"""text_cleaner.py の単体テスト。"""

from src.pipeline.text_cleaner import (
    clean_aozora_markup,
    extract_clean_sentences,
    split_paragraph_into_sentences,
    strip_header_footer,
)


def test_strip_header_footer_and_markup() -> None:
    sample = """坊っちゃん
夏目漱石

-------------------------------------------------------
【テキスト中に現れる記号について】

《》：ルビ
［＃］：入力者注
-------------------------------------------------------

　親譲《おやゆず》りの無鉄砲《むてっぽう》で小供の時から損ばかりしている。［＃「小供」はママ］
　｜小学校《しょうがっこう》に居る時分学校の二階から飛び降りて一週間ほど腰を抜かした事がある。
　「おい、大丈夫か。気をつけろよ！」と友人が言った。

底本：「坊っちゃん」新潮文庫、新潮社
1950（昭和25）年発行
"""
    sentences = extract_clean_sentences(sample.encode("cp932"))
    assert sentences == [
        "親譲りの無鉄砲で小供の時から損ばかりしている。",
        "小学校に居る時分学校の二階から飛び降りて一週間ほど腰を抜かした事がある。",
        "「おい、大丈夫か。気をつけろよ！」と友人が言った。",
    ], f"Unexpected sentences: {sentences}"


def test_nested_notes_and_gaiji() -> None:
    text = "これは※［＃「口＋鳥」、第3水準1-15-82］テスト［＃「テスト」に傍点］です。"
    cleaned = clean_aozora_markup(text)
    assert cleaned == "これはテストです。", f"Unexpected cleaned: {cleaned}"


def test_split_preserves_quotes() -> None:
    para = "彼は「今日は晴れだ。散歩しよう。」と言った。そして外へ出た。"
    sents = split_paragraph_into_sentences(para)
    assert sents == [
        "彼は「今日は晴れだ。散歩しよう。」と言った。",
        "そして外へ出た。",
    ]


if __name__ == "__main__":
    test_strip_header_footer_and_markup()
    test_nested_notes_and_gaiji()
    test_split_preserves_quotes()
    print("All text_cleaner tests passed!")
