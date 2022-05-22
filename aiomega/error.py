from typing import Union


class MegaRequestError(Exception):
    def __init__(self, code: int, message: str, *args) -> None:
        self.code = code
        self.message = message

        super().__init__(*args)

    def __str__(self):
        return self.message


class MegaNodeNotFound(Exception):
    def __init__(self, node: Union[str, int], *args) -> None:
        self.node = node
        super().__init__(*args)

    def __str__(self) -> str:
        if isinstance(self.node, int):
            return f"The node with the handle {self.node} doesn't exists anymore"
        return f"The node with path {self.node} doesn't exists anymore"
