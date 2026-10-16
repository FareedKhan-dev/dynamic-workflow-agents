def pig_latin(word: str) -> str:
    """Compute the piglatin of a given string.

    https://en.wikipedia.org/wiki/Pig_Latin

    Usage examples:
    >>> pig_latin("pig")
    'igpay'
    >>> pig_latin("banana")
    'ananabay'
    >>> pig_latin("friends")
    'iendsfray'
    >>> pig_latin("string")
    'ingstray'
    >>> pig_latin("eat")
    'eatway'
    >>> pig_latin("omelet")
    'omeletway'
    >>> pig_latin("are")
    'areway'
    """
    if not (word or "").strip():
        return ""
    word = word.lower()
    if word[0] in "aeiou":
        return f"{word}way"
    for i, char in enumerate(word):  # noqa: B007
        if char in "aeiou":
            break
    return f"{word[i:]}{word[:i]}ay"


if __name__ == "__main__":
    print(f"{pig_latin('friends') = }")
    word = input("Enter a word: ")
    print(f"{pig_latin(word) = }")
