"""
A pure Python implementation of the insertion sort algorithm

This algorithm sorts a collection by comparing adjacent elements.
When it finds that order is not respected, it moves the element compared
backward until the order is correct.  It then goes back directly to the
element's initial position resuming forward comparison.

For doctests run following command:
python3 -m doctest -v insertion_sort.py

For manual testing run:
python3 insertion_sort.py
"""

from collections.abc import MutableSequence
from typing import Any, Protocol, TypeVar


class Comparable(Protocol):
    def __lt__(self, other: Any, /) -> bool: ...


T = TypeVar("T", bound=Comparable)


def insertion_sort[T: Comparable](collection: MutableSequence[T]) -> MutableSequence[T]:
    """A pure Python implementation of the insertion sort algorithm

    :param collection: some mutable ordered collection with heterogeneous
    comparable items inside
    :return: the same collection ordered by ascending

    Complexity Analysis:
        Time Complexity:
            - Best Case: O(n) when the collection is already sorted
            - Average Case: O(n^2)
            - Worst Case: O(n^2) when the collection is sorted in reverse order

        Space Complexity:
            - O(1) because the algorithm sorts the collection in place and
              uses only a constant amount of additional memory

    Examples:
    >>> insertion_sort([-2, -5, -45]) == sorted([-2, -5, -45])
    True
    >>> values = [4, 2, 7, 1]
    >>> result = insertion_sort(values)

    Equal-priority items retain their original relative order:
    >>> from dataclasses import dataclass, field
    >>> @dataclass(order=True)
    ... class Item:
    ...     priority: int
    ...     label: str = field(compare=False)
    >>> items = [Item(2, "A"), Item(1, "X"), Item(2, "B"), Item(1, "Y")]
    >>> other = [Item(2, "B"), Item(1, "Y"), Item(2, "A"), Item(1, "X")]

    >>> import random
    >>> collection = random.sample(range(-50, 50), 100)
    >>> import string
    >>> collection = random.choices(string.ascii_letters + string.digits, k=100)
    >>> insertion_sort(collection) == sorted(collection)
    True
    """

    for insert_index in range(1, len(collection)):
        insert_value = collection[insert_index]
        while insert_index > 0 and insert_value < collection[insert_index - 1]:
            collection[insert_index] = collection[insert_index - 1]
            insert_index -= 1
        collection[insert_index] = insert_value
    return collection


if __name__ == "__main__":
    from doctest import testmod

    testmod()

    user_input = input("Enter numbers separated by a comma:\n").strip()
    unsorted = [int(item) for item in user_input.split(",")]
    print(f"{insertion_sort(unsorted) = }")
