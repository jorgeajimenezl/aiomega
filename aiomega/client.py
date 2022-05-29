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
        if self.is_logged_in():
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
        """
        Return the object `MegaNode` with the specified path or handle.

        Parameters:
            node (``Union[in, str, MegaNode]``):
                Path or handle to remote node.

        Returns:
            :obj:`MegaNode`: The MegaNode object that represent the node.
        """

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
        """
        Log in to a MEGA account.
        """
        await self._request(self.api.login, email, password)

    async def logout(self) -> None:
        """
        Logout of the MEGA account invalidating the session.
        """
        await self._request(self.api.logout)

    def is_logged_in(self) -> bool:
        """
        Check if the Mega object is logged in.

        Returns:
            :obj:`bool`: `False` if not logged in, Otherwise, a `True`.
        """
        return True if self.api.isLoggedIn() > 0 else False

    def is_online(self) -> bool:
        """
        Check if the connection with MEGA servers is OK.
        It can briefly return false even if the connection is good enough when some 
        storage servers are temporarily not available or the load of API servers is high.

        Returns:
            :obj:`bool`: `True` if the connection is perfectly OK, otherwise `False`.
        """
        return self.api.isOnline()

    async def account_details(self) -> MegaAccountDetails:
        """
        Get details about the MEGA account.

        Returns:
            :obj:`MegaAccountDetails`: Object with account details.
        """

        req = await self._request(self.api.getAccountDetails)
        return req.getMegaAccountDetails()

    async def create_folder(
        self, name: str, parent: Union[int, str, MegaNode] = "/"
    ) -> int:
        """
        Create a folder in the MEGA account.

        Parameters:
            name (``str``):
                Name of the new folder.

            parent (``Union[in, str, MegaNode]``):
                Parent folder.

        Returns:
            :obj:`int`: Handle of the new folder.
        """

        parent = await self.get_node(parent)
        req = await self._request(self.api.createFolder, name, parent)
        return req.getNodeHandle()

    async def remove(self, node: Union[int, str, MegaNode]) -> None:
        """
        Remove a node from the MEGA account.

        This function doesn't move the node to the Rubbish Bin, it fully removes the node. 
        To move the node to the Rubbish Bin use `move_node(...)`

        If the node has previous versions, they will be deleted too

        Parameters:
            node (``Union[in, str, MegaNode]``):
                Node to remove.
        """

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
        """
        Upload a file or folder with a custom name.

        Parameters:
            parent (``Union[int, str, MegaNode]``):
                Parent node for the file or folder in the MEGA account.

            local_path (``str``):
                Local path of the file.

            filename (``str``, *optional*):
                Custom file name for the file in MEGA

            progress (``callable``, *optional*):
                Pass a callback function to view the file transmission progress.
                The function must take *(current, total, speed)* as positional 
                arguments (look at Other Parameters below for a detailed description) and will 
                be called back each time a new file chunk has been successfully transmitted.

            progress_args (``tuple``, *optional*):
                Extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope.

        Returns:
            :obj:`MegaTransfer`: An object with information about the transference.

        Other Parameters:
            current (``int``):
                The amount of bytes transmitted so far.

            total (``int``):
                The total size of the file.

            speed (``int``):
                The actual speed of the transmission.

            *args (``tuple``, *optional*):
                Extra custom arguments as defined in the ``progress_args`` parameter.
                You can either keep ``*args`` or add every single extra argument in your function signature.

        Example:
            .. code-block:: python

                ...
                def progress(current, total, _):
                    print(f"{current * 100 / total:.1f}%")

                await client.upload('/file', '/path/to/file', progress=progress)
                ...
        """

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
        """
        Download a file or a folder from MEGA.

        Parameters:
            node (``Union[int, str, MegaNode]``):
                Node that identifies the file or folder

            local_path (``str``):
                Destination path for the file or folder If this path is a local folder, it must 
                end with a '\' or '/' character and the file name in MEGA will be used to store 
                a file inside that folder. If the path doesn't finish with one of these characters, 
                the file will be downloaded to a file in that path.

            progress (``callable``, *optional*):
                Pass a callback function to view the file transmission progress.
                The function must take *(current, total, speed)* as positional arguments (look at 
                Other Parameters below for a detailed description) and will be called back each 
                time a new file chunk has been successfully
                transmitted.

            progress_args (``tuple``, *optional*):
                Extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope.

        Returns:
            :obj:`MegaTransfer`: An object with information about the transference.

        Other Parameters:
            current (``int``):
                The amount of bytes transmitted so far.

            total (``int``):
                The total size of the file.

            speed (``int``):
                The actual speed of the transmission.

            *args (``tuple``, *optional*):
                Extra custom arguments as defined in the ``progress_args`` parameter.
                You can either keep ``*args`` or add every single extra argument in your function signature.

        Example:
            .. code-block:: python

                ...
                def progress(current, total, _):
                    print(f"{current * 100 / total:.1f}%")

                await client.download('/file', '/path/to/file', progress=progress)
                ...
        """

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
        [WARNING]: Worst performance, use download

        Start an streaming download for a file in MEGA. This return an iterator over the chunks
        of the file.

        Parameters:
            node (``Union[int, str, MegaNode]``):
                Node that identifies the file or folder.

            offset (``int``):
                First byte to download from the file.

            limit (``int``):
                Size of the data to download.

            chunk_size (``int``):
                Size of the byte chunks returned by the generator. The last chunk can have
                less bytes than the specified here.

            progress (``callable``, *optional*):
                Pass a callback function to view the file transmission progress.
                The function must take *(current, total, speed)* as positional arguments (look at 
                Other Parameters below for a detailed description) and will be called back each 
                time a new file chunk has been successfully
                transmitted.

            progress_args (``tuple``, *optional*):
                Extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope.

        Returns:
            :obj:`Generator[bytes]`: Return a generator to get file data

        Other Parameters:
            current (``int``):
                The amount of bytes transmitted so far.

            total (``int``):
                The total size of the file.

            speed (``int``):
                The actual speed of the transmission.

            *args (``tuple``, *optional*):
                Extra custom arguments as defined in the ``progress_args`` parameter.
                You can either keep ``*args`` or add every single extra argument in your function signature.

        Example:
            .. code-block:: python

                ...
                def progress(current, total, _):
                    print(f"{current * 100 / total:.1f}%")

                with open("file", "wb") as file:
                    async for chunk in mega.streaming("/path/to/file", progress=progress):
                        file.write(chunk)
                ...
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
    ) -> None:
        """
        Share or stop sharing a folder in MEGA with another user using his email.

        To share a folder with an user, set the desired access level in the level parameter. If
        you want to stop sharing a folder use the access level `MegaShare.ACCESS_UNKNOWN`

        Parameters:
            node (``Union[int, str, MegaNode]``):
                The folder to share. It must be a non-root folder.

            user (``Union[str, MegaUser]``):
                User that receives the shared folder, if is a str then, the email of the user that
                receives the shared folder. If it doesn't have a MEGA account, the folder will be shared
                anyway and the user will be invited to register an account.

            level (``MegaShare``):
                Permissions that are granted to the user Valid values for this parameter:

                    - `MegaShare.ACCESS_UNKNOWN` = -1 Stop sharing a folder with this user
                    - `MegaShare.ACCESS_READ` = 0
                    - `MegaShare.ACCESS_READWRITE` = 1
                    - `MegaShare.ACCESS_FULL` = 2
                    - `MegaShare.ACCESS_OWNER` = 3

        """

        await self._request(self.api.share, node, user, level)

    async def why_am_i_blocked(self) -> Tuple[int, str]:
        """
        Check the reason of being blocked.

        Returns:
            :obj:`Tuple[int, str]`: An tuple with the reason code and the text.
        """

        req = await self._request(self.api.whyAmIBlocked)
        return (req.getNumber(), req.getText())

    async def retry_transfer(
        self,
        transfer: MegaTransfer,
        progress: Optional[Callable[[int, int, int, Tuple], None]] = None,
        progress_args: Optional[Tuple] = (),
    ) -> MegaTransfer:
        """
        Retry a transfer.

        This function allows to start a transfer based on a `MegaTransfer object`. It can be used, 
        for example, to retry transfers that finished with an error. To do it, you can retain the 
        MegaTransfer object in onTransferFinish (calling `MegaTransfer.copy(...)` to take the ownership) 
        and use it later with this function.

        Returns:
            :obj:`MegaTransfer`: The new MegaTransfer object.
        """

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
        new_name: Optional[str] = None,
    ) -> None:
        """
        Move a node in the MEGA account changing the file name.

        Parameters:
            node (``Union[int, str, MegaNode]``):
                Node to move.

            new_parent (``Union[int, str, MegaNode]``):
                New parent for the node.

            new_name (``str``, *optional*):
                Name for the new node.
        """

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
        """
        Copy a node in the MEGA account changing the file name.

        Parameters:
            node (``Union[int, str, MegaNode]``):
                Node to copy.

            new_parent (``Union[int, str, MegaNode]``):
                Parent for the new node.

            new_name (``str``, *optional*):
                Name for the new node.
        """

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
        """
        Generate a public link of a file/folder in MEGA.

        Parameters:
            node (``Union[int, str, MegaNode]``):
                Node to get the public link.

            expire_time (``int``):
                Unix timestamp until the public link will be valid.

            writable (``bool``):
                If the link should be writable.

            mega_hosted (``bool``):
                If the share key should be shared with MEGA.

        Returns:
            :obj:`str`: Public link
        """
        node = self.get_node(node)
        req = await self._request(
            self.api.exportNode, node, expire_time, writable, mega_hosted
        )

        return req.getLink()

    async def get_public_node(self, link: str) -> MegaNode:
        """
        Get a MegaNode from a public link to a file.

        A public node can be imported using `copy_node(...)` or downloaded using `download(...)`

        Parameters:
            link (``str``):
                Public link to a file in MEGA.

        Returns:
            :obj:`MegaNode`: Public `MegaNode` corresponding to the public link
        """

        req = await self._request(self.api.getPublicNode, link)
        return req.getPublicMegaNode()
