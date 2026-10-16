"""
In this problem, we want to determine all possible subsequences
of the given sequence. We use backtracking to solve this problem.

Time complexity: O(2^n),
where n denotes the length of the given sequence.
"""

from __future__ import annotations

from typing import Any


def generate_all_subsequences(sequence: list[Any]) -> None:
    """
    Generate and print all possible subsequences of the given sequence.

    """

    create_state_space_tree(sequence, [], 0)


def create_state_space_tree(
    sequence: list[Any], current_subsequence: list[Any], index: int
) -> None:
    """
    Creates a state space tree to iterate through each branch using DFS.
    We know that each state has exactly two children.
    It terminates when it reaches the end of the given sequence.

    :param sequence: The input sequence for which subsequences are generated.
    :param current_subsequence: The current subsequence being built.
    :param index: The current index in the sequence.

    Example:
    >>> sequence = [3, 2, 1]
    >>> current_subsequence = []

    >>> sequence = ["A", "B"]
    >>> current_subsequence = []

    >>> sequence = []
    >>> current_subsequence = []
    >>> create_state_space_tree(sequence, current_subsequence, 0)
    []

    >>> sequence = [1, 2, 3, 4]
    >>> current_subsequence = []
    """

    if index == len(sequence):
        print(current_subsequence)
        return

    create_state_space_tree(sequence, current_subsequence, index + 1)
    current_subsequence.append(sequence[index])
    create_state_space_tree(sequence, current_subsequence, index + 1)
    current_subsequence.pop()


if __name__ == "__main__":
    seq: list[Any] = [1, 2, 3]
    generate_all_subsequences(seq)

    seq.clear()
    seq.extend(["A", "B", "C"])
    generate_all_subsequences(seq)
