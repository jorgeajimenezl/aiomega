import asyncio
import functools
import inspect
import logging
import os
from types import TracebackType

from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Generic,
    List,
    Optional,
    Type,
    Union,
    Tuple,
)
from .megasdk import (
    MegaApi,
    MegaRequestListener,
    MegaTransferListener,
    MegaProxy,
    MegaRequest,
    MegaTransfer,
    MegaError,
    MegaAccountDetails,
    MegaNode,
    MegaUser,
    MegaShare,
)

from .error import MegaNodeNotFound, MegaRequestError


class AsyncEvent(asyncio.Event):
    def set(self) -> None:
        self._loop.call_soon_threadsafe(super().set)


class _RequestListener(MegaRequestListener):
    def __init__(self) -> None:
        self.finish_event: AsyncEvent = AsyncEvent()
        self.request: MegaRequest = None
        self.error: MegaError = None

        super().__init__()

    def onRequestStart(self, api: MegaApi, request: MegaRequest) -> None:
        logging.info("Request start ({})".format(request))

    def onRequestFinish(
        self, api: MegaApi, request: MegaRequest, error: MegaError
    ) -> None:
        logging.info("Request finished ({}); Result: {}".format(request, error))

        self.request = request.copy()
        self.error = error.copy()
        self.finish_event.set()

    def onRequestTemporaryError(
        self, api: MegaApi, request: MegaRequest, error: MegaError
    ) -> None:
        logging.info("Request temporary error ({}); Error: {}".format(request, error))


class _TransferListener(MegaTransferListener):
    def __init__(
        self,
        progress: Optional[Callable[[int, int, int, Tuple], None]] = None,
        progress_args: Optional[Tuple] = (),
    ) -> None:
        self.finish_event: AsyncEvent = AsyncEvent()
        self.transfer: MegaTransfer = None
        self.error: MegaError = None
        self.loop = asyncio.get_event_loop()
        self.progress = progress
        self.progress_args = progress_args

        super().__init__()

    def onTransferStart(self, api: MegaApi, transfer: MegaTransfer) -> None:
        logging.info("Transfer start ({})".format(transfer))

    def onTransferFinish(
        self, api: MegaApi, transfer: MegaTransfer, error: MegaError
    ) -> None:
        logging.info(
            "Transfer finished ({}); Result: {}".format(
                transfer, transfer.getFileName(), error
            )
        )

        self.transfer = transfer.copy()
        self.error = error.copy()
        self.finish_event.set()

    def onTransferUpdate(self, api: MegaApi, transfer: MegaTransfer):
        logging.info(
            "Transfer update ({} {});"
            " Progress: {} KB of {} KB, {} KB/s".format(
                transfer,
                transfer.getFileName(),
                transfer.getTransferredBytes() / 1024,
                transfer.getTotalBytes() / 1024,
                transfer.getSpeed() / 1024,
            )
        )

        func = functools.partial(
            self.progress,
            transfer.getTransferredBytes(),
            transfer.getTotalBytes(),
            transfer.getSpeed(),
            *self.progress_args,
        )

        # Schedule
        if inspect.iscoroutinefunction(self.progress):
            asyncio.run_coroutine_threadsafe(func(), loop=self.loop)
        else:
            self.loop.call_soon_threadsafe(func)

    def onTransferTemporaryError(
        self, api: MegaApi, transfer: MegaTransfer, error: MegaError
    ):
        logging.info(
            "Transfer temporary error ({} {}); Error: {}".format(
                transfer, transfer.getFileName(), error
            )
        )


class _TransferStreamingListener(_TransferListener):
    def __init__(
        self,
        progress: Optional[Callable[[int, int, int, Tuple], None]] = None,
        progress_args: Optional[Tuple] = (),
    ) -> None:
        super().__init__(progress, progress_args)

        self.pipein, self.pipeout = os.pipe()

    def onTransferData(
        self, api: MegaApi, transfer: MegaTransfer, buffer: bytes, size: int
    ) -> bool:
        n = 0
        while n < size:
            n += os.write(self.pipeout, buffer)
        assert n == size, "Unable to establish connection with read pipe extreme"
        return True

    def onTransferFinish(
        self, api: MegaApi, transfer: MegaTransfer, error: MegaError
    ) -> None:
        os.close(self.pipeout)
        super().onTransferFinish(api, transfer, error)


class Mega(object):
    def __init__(
        self,
        app_key: str,
        base_path: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: Optional[int] = None,
        proxy: Optional[Dict[str, Union[str, None]]] = None,
        http_only: bool = False,
        **kwargs,
    ) -> None:
        self.api = MegaApi(app_key, base_path, user_agent)

        # Push requests
        if proxy:
            assert (
                "url" in proxy
            ), "Proxy dictionary must contains almost the url component"

            p = MegaProxy()
            p.setProxyType(MegaProxy.PROXY_CUSTOM)
            p.setProxyURL(proxy.get("url"))
            p.setCredentials(proxy.get("username", None), proxy.get("password", None))
            self.api.setProxySettings(p)

        self.api.useHttpsOnly(http_only)

    def __enter__(self) -> None:
        raise TypeError("Use async with instead")

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """
        Unable to call because you must use asyn with statement
        """
        pass

    async def __aenter__(self) -> "Mega":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        await self.logout()

    async def _request(self, func: Callable[[Any], None], *args) -> MegaRequest:
        listener = _RequestListener()
        func(*args, listener)
        await listener.finish_event.wait()

        code = listener.error.getErrorCode()
        if code != MegaError.API_OK:
            raise MegaRequestError(code, listener.error.getErrorString())
        return listener.request

    async def _transfer(
        self,
        func: Callable[[Any], None],
        *args,
        progress: Optional[Callable[[int, int, int, Tuple], None]] = None,
        progress_args: Optional[Tuple] = (),
    ) -> MegaTransfer:
        listener = _TransferListener(progress, progress_args)
        func(*args, listener)
        await listener.finish_event.wait()

        code = listener.error.getErrorCode()
        if code != MegaError.API_OK:
            raise MegaRequestError(code, listener.error.getErrorString())
        return listener.transfer

    async def get_node(self, node: Union[int, str, MegaNode]) -> MegaNode:
        if not isinstance(node, MegaNode) and not self.api.isFilesystemAvailable():
            await self._request(self.api.fetchNodes)

        if isinstance(node, MegaNode):
            r = node
        elif isinstance(node, str):
            r = self.api.getNodeByPath(node)
        elif isinstance(node, int):
            r = self.api.getNodeByHandle(node)
        else:
            raise TypeError(
                "node must be a string, integer (MegaHandler) or a MegaNode"
            )

        if r is None:
            raise MegaNodeNotFound(node)

        return r

    async def login(self, email: str, password: str) -> None:
        await self._request(self.api.login, email, password)

    async def logout(self) -> None:
        await self._request(self.api.logout)

    def is_logged_in(self) -> bool:
        return True if self.api.isLoggedIn() > 0 else False

    def is_online(self) -> bool:
        return self.api.isOnline()

    async def account_details(self) -> MegaAccountDetails:
        req = await self._request(self.api.getAccountDetails)
        return req.getMegaAccountDetails()

    async def create_folder(
        self, name: str, parent: Union[int, str, MegaNode] = "/"
    ) -> int:
        parent = await self.get_node(parent)
        req = await self._request(self.api.createFolder, name, parent)
        return req.getNodeHandle()

    async def remove(self, node: Union[int, str, MegaNode]) -> None:
        node = await self.get_node(node)
        await self._request(self.api.remove, node)

    async def upload(
        self,
        parent: Union[int, str, MegaNode],
        local_path: str,
        filename: Optional[str] = None,
        progress: Optional[Callable[[int, int, int, Tuple], None]] = None,
        progress_args: Optional[Tuple] = (),
    ) -> MegaTransfer:
        parent = await self.get_node(parent)
        filename = filename or os.path.basename(local_path)
        transfer = await self._transfer(
            self.api.startUpload,
            local_path,
            parent,
            filename,
            progress=progress,
            progress_args=progress_args,
        )

        return transfer

    async def download(
        self,
        node: Union[int, str, MegaNode],
        local_path: str,
        progress: Optional[Callable[[int, int, int, Tuple], None]] = None,
        progress_args: Optional[Tuple] = (),
    ) -> MegaTransfer:
        node = await self.get_node(node)
        transfer = await self._transfer(
            self.api.startDownload,
            local_path,
            node,
            progress=progress,
            progress_args=progress_args,
        )

        return transfer

    async def streaming(
        self,
        node: Union[int, str, MegaNode],
        offset: int = 0,
        limit: int = None,
        chunk_size: int = 2097152,
        progress: Optional[Callable[[int, int, int, Tuple], None]] = None,
        progress_args: Optional[Tuple] = (),
    ) -> Generator[bytes, None, None]:
        """
        WARNING: Wrost performance, use download
        """
        node = await self.get_node(node)

        # Implemented streaming
        listener = _TransferStreamingListener(progress, progress_args)
        limit = limit or node.getSize()
        self.api.startStreaming(node, offset, limit, listener)

        loop = listener.loop
        reader = asyncio.StreamReader(loop=loop)
        reader_protocol = asyncio.StreamReaderProtocol(reader)

        # Setup pipe
        # FIX: Use no-block call in write pipe side using some schedule form
        with os.fdopen(listener.pipein, "rb") as pipe:
            await loop.connect_read_pipe(lambda: reader_protocol, pipe)

            # Main loop to generate all chunks
            while not reader.at_eof():
                chunk = await reader.read(chunk_size)
                yield chunk

        # Wait to transfer finish event
        await listener.finish_event.wait()

        code = listener.error.getErrorCode()
        if code != MegaError.API_OK:
            raise MegaRequestError(code, listener.error.getErrorString())

    async def share(
        self,
        node: Union[int, str, MegaNode],
        user: Union[str, MegaUser],
        level: MegaShare,
    ):
        await self._request(self.api.share, node, user, level)

    async def why_am_i_blocked(self) -> Tuple[int, str]:
        req = await self._request(self.api.whyAmIBlocked)
        return (req.getNumber(), req.getText())

    async def retry_transfer(
        self,
        transfer: MegaTransfer,
        progress: Optional[Callable[[int, int, int, Tuple], None]] = None,
        progress_args: Optional[Tuple] = (),
    ):
        transfer = await self._transfer(
            self.api.retryTransfer,
            transfer,
            progress=progress,
            progress_args=progress_args,
        )

        return transfer

    async def move_node(
        self,
        node: Union[str, int, MegaNode],
        new_parent: Union[str, int, MegaNode],
        new_name: str = None,
    ) -> None:
        node = self.get_node(node)
        new_parent = self.get_node(new_parent)
        if new_name is None:
            await self._request(self.api.moveNode, node, new_parent)
        else:
            await self._request(self.api.moveNode, node, new_parent, new_name)

    async def copy_node(
        self,
        node: Union[str, int, MegaNode],
        new_parent: Union[str, int, MegaNode],
        new_name: str = None,
    ) -> None:
        node = self.get_node(node)
        new_parent = self.get_node(new_parent)
        if new_name is None:
            await self._request(self.api.copyNode, node, new_parent)
        else:
            await self._request(self.api.copyNode, node, new_parent, new_name)

    async def export_node(
        self,
        node: Union[str, int, MegaNode],
        expire_time: int = (1 << 63) - 1,
        writable: bool = False,
        mega_hosted: bool = True,
    ) -> str:
        node = self.get_node(node)
        req = await self._request(
            self.api.exportNode, node, expire_time, writable, mega_hosted
        )

        return req.getLink()

    async def get_public_node(self, link: str) -> MegaNode:
        req = await self._request(self.api.getPublicNode, link)
        return req.getPublicMegaNode()
