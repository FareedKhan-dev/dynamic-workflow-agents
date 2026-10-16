def get_highest_set_bit_position(number: int) -> int:
    """
    Returns position of the highest set bit of a number.
    Ref - https://graphics.stanford.edu/~seander/bithacks.html#IntegerLogObvious
    >>> get_highest_set_bit_position(25)
    5
    >>> get_highest_set_bit_position(37)
    6
    >>> get_highest_set_bit_position(1)
    1
    >>> get_highest_set_bit_position(0)
    0
    """
    if not isinstance(number, int):
        raise TypeError("Input value must be an 'int' type")

    position = 0
    while number:
        position += 1
        number >>= 1

    return position


if __name__ == "__main__":
    import doctest

    doctest.testmod()
