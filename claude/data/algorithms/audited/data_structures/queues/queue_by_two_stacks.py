"""Queue implementation using two stacks"""

from collections.abc import Iterable


class QueueByTwoStacks[T]:
    def __init__(self, iterable: Iterable[T] | None = None) -> None:
        """
        >>> QueueByTwoStacks([10, 20, 30])
        Queue((10, 20, 30))
        """
        self._stack1: list[T] = list(iterable or [])
        self._stack2: list[T] = []

    def __len__(self) -> int:
        """
        >>> from string import ascii_lowercase
        >>> queue = QueueByTwoStacks()
        >>> for i in range(1, 11):
        ...     queue.put(i)
        ...
        >>> for i in range(2):
        ...   queue.get()
        1
        2
        >>> len(queue)
        8
        """

        return len(self._stack1) + len(self._stack2)

    def __repr__(self) -> str:
        """
        >>> queue = QueueByTwoStacks()
        >>> queue
        Queue(())
        >>> str(queue)
        'Queue(())'
        >>> queue.put(10)
        >>> queue
        Queue((10,))
        >>> queue.put(20)
        >>> queue.put(30)
        >>> queue
        Queue((10, 20, 30))
        """
        return f"Queue({tuple(self._stack2[::-1] + self._stack1)})"

    def put(self, item: T) -> None:
        """
        Put `item` into the Queue

        >>> queue = QueueByTwoStacks()
        >>> queue.put(10)
        >>> queue.put(20)
        >>> len(queue)
        2
        >>> queue
        Queue((10, 20))
        """

        self._stack1.append(item)

    def get(self) -> T:
        """
        Get `item` from the Queue

        >>> queue = QueueByTwoStacks((10, 20, 30))
        >>> queue.get()
        10
        >>> queue.put(40)
        >>> queue.get()
        20
        """

        # To reduce number of attribute look-ups in `while` loop.
        stack1_pop = self._stack1.pop
        stack2_append = self._stack2.append

        if not self._stack2:
            while self._stack1:
                stack2_append(stack1_pop())

        if not self._stack2:
            raise IndexError("Queue is empty")
        return self._stack2.pop()


if __name__ == "__main__":
    from doctest import testmod

    testmod()
