"""A Stack using a linked list like structure"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TypeVar

T = TypeVar("T")


class Node[T]:
    def __init__(self, data: T) -> None:
        self.data = data
        self.next: Node[T] | None = None

    def __str__(self) -> str:
        return f"{self.data}"


class LinkedStack[T]:
    """
    Linked List Stack implementing push (to top),
    pop (from top) and is_empty

    >>> stack = LinkedStack()
    >>> stack.push(5)
    >>> stack.push(9)
    >>> stack.push('python')
    >>> stack.push('algorithms')
    """

    def __init__(self) -> None:
        self.top: Node[T] | None = None

    def __iter__(self) -> Iterator[T]:
        node = self.top
        while node:
            yield node.data
            node = node.next

    def __str__(self) -> str:
        """
        >>> stack = LinkedStack()
        >>> stack.push("c")
        >>> stack.push("b")
        >>> stack.push("a")
        """
        return "->".join([str(item) for item in self])

    def __len__(self) -> int:
        """
        >>> stack = LinkedStack()
        >>> stack.push("c")
        >>> stack.push("b")
        >>> stack.push("a")
        >>> len(stack) == 3
        True
        """
        return len(tuple(iter(self)))

    def is_empty(self) -> bool:
        """
        >>> stack = LinkedStack()
        >>> stack.push(1)
        """
        return self.top is None

    def push(self, item: T) -> None:
        """
        >>> stack = LinkedStack()
        >>> stack.push("Python")
        >>> stack.push("Java")
        >>> stack.push("C")
        """
        node = Node(item)
        if not self.is_empty():
            node.next = self.top
        self.top = node

    def pop(self) -> T:
        """
        >>> stack = LinkedStack()
        >>> stack.push("c")
        >>> stack.push("b")
        >>> stack.push("a")
        """
        if self.is_empty():
            raise IndexError("pop from empty stack")
        assert isinstance(self.top, Node)
        pop_node = self.top
        self.top = self.top.next
        return pop_node.data

    def peek(self) -> T:
        """
        >>> stack = LinkedStack()
        >>> stack.push("Java")
        >>> stack.push("C")
        >>> stack.push("Python")
        >>> stack.peek()
        'Python'
        """
        if self.is_empty():
            raise IndexError("peek from empty stack")

        assert self.top is not None
        return self.top.data

    def clear(self) -> None:
        """
        >>> stack = LinkedStack()
        >>> stack.push("Java")
        >>> stack.push("C")
        >>> stack.push("Python")
        >>> stack.clear()
        """
        self.top = None


if __name__ == "__main__":
    from doctest import testmod

    testmod()
