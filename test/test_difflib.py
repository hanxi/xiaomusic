import difflib

from xiaomusic.utils import (
    find_best_match,
    keyword_detection,
)

if __name__ == "__main__":
    user_input = "八年的爱"
    s1 = "冰冰超人 - 八年的爱新版"
    s2 = "冰冰超人 - 八年的爱"
    r1 = difflib.SequenceMatcher(None, s1, user_input).ratio()
    r2 = difflib.SequenceMatcher(None, s2, user_input).ratio()
    print(s1, r1)
    print(s2, r2)

    s3 = "其他"
    str_list = [s2, s1, s3]
    matches, remains = keyword_detection(user_input, str_list, n=10)
    print(matches, remains)

    extra_search_index = {}
    extra_search_index["1"] = s1
    extra_search_index["2"] = s2
    extra_search_index["3"] = s3
    real_names = find_best_match(
        user_input,
        str_list,
        cutoff=0.4,
        n=100,
        extra_search_index=extra_search_index,
    )
    print(real_names)
