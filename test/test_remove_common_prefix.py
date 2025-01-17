import re


def removepre(filename):
    match = re.search(r"^[pP]?(\d+)\s+\d*(.+?)\.(.*$)", filename.strip())
    new_filename = filename
    if match:
        num = match.group(1)
        name = match.group(2).replace(".", " ").strip()
        suffix = match.group(3)
        # print(name)
        # print(num)
        # print(suffix)
        new_filename = f"{num}.{name}.{suffix}"

    print(filename, "=>", new_filename)


if __name__ == "__main__":
    removepre(" 17 《白色风车》.mp3")
    removepre(" 17 《白色风车》.mp3")
    removepre(" 17 17 《白色风车》.mp3")
    removepre(" 17 17 《白色风车》.mp3")

    removepre(" 18 风车.mp3")
    removepre(" 18 色风车.mp3")
    removepre(" 18 18 你好.mp3")
    removepre(" 18 18 我好.mp3")
    removepre("p09 009. 梁静茹-亲亲.mp3")
