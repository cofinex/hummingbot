import asyncio
import logging
from typing import Optional

from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.logger import HummingbotLogger


class UserStreamTracker:
    _ust_logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._ust_logger is None:
            cls._ust_logger = logging.getLogger(__name__)
        return cls._ust_logger

    def __init__(self, data_source: UserStreamTrackerDataSource):
        self._user_stream: asyncio.Queue = asyncio.Queue()
        self._data_source = data_source
        self._user_stream_tracking_task: Optional[asyncio.Task] = None

    @property
    def data_source(self) -> UserStreamTrackerDataSource:
        return self._data_source

    @property
    def last_recv_time(self) -> float:
        return self.data_source.last_recv_time

    def start(self):
        """Start the user stream tracking task."""
        # Commented out verbose debug logging - keep minimal logging for errors only
        # self.logger().info("UserStreamTracker.start() called")

        # Stop any existing task
        self.stop()

        # Commented out verbose debug logging
        # self.logger().info("UserStreamTracker.start() - creating task for listen_for_user_stream")
        try:
            # Create the coroutine first
            coro = self.data_source.listen_for_user_stream(self._user_stream)
            # Commented out verbose debug logging
            # self.logger().info(f"UserStreamTracker.start() - coroutine created: {coro}")

            # Verify coroutine is actually a coroutine
            import inspect
            if not inspect.iscoroutine(coro):
                self.logger().error(f"ERROR: coro is not a coroutine! type={type(coro)}, value={coro}")
                raise TypeError(f"listen_for_user_stream() must return a coroutine, got {type(coro)}")

            # Create the task directly (like OrderBookTracker.start())
            # Commented out verbose debug logging
            # _loop = asyncio.get_event_loop()
            # self.logger().info(f"UserStreamTracker.start() - event loop: {_loop}, running: {_loop.is_running()}")
            task = safe_ensure_future(coro)
            self._user_stream_tracking_task = task
            # Commented out verbose debug logging
            # self.logger().info(f"UserStreamTracker.start() - task created: {task}, done: {task.done()}, cancelled: {task.cancelled()}")
            # try:
            #     _running_loop = asyncio.get_running_loop()
            # except RuntimeError:
            #     _running_loop = None
            # Commented out verbose debug logging
            # self.logger().info(
            #     "UserStreamTracker.start() - task loop=%s, running loop=%s",
            #     task.get_loop(),
            #     running_loop,
            # )

            # Add a done callback to catch exceptions (like OrderBookTracker)
            def task_done_callback(fut):
                try:
                    if fut.cancelled():
                        self.logger().warning("UserStreamTracker task was cancelled")
                    elif fut.exception():
                        exc = fut.exception()
                        self.logger().error(f"UserStreamTracker task raised exception: {exc}", exc_info=True)
                    # Note: Don't log completion as it's noisy - tasks complete normally
                except Exception as e:
                    self.logger().error(f"Error in task_done_callback: {e}", exc_info=True)

            task.add_done_callback(task_done_callback)
            # Commented out verbose debug logging
            # self.logger().info(f"UserStreamTracker.start() completed - task created: {task}")

        except Exception as e:
            self.logger().error(f"UserStreamTracker.start() - Error creating task: {e}", exc_info=True)
            raise

    def stop(self):
        """Stop the user stream tracking task and clean up resources."""
        if self._user_stream_tracking_task is not None and not self._user_stream_tracking_task.done():
            self._user_stream_tracking_task.cancel()

        # Note: We don't await the task here since this is now a synchronous method
        # The task cancellation will be handled by the event loop

        self._user_stream_tracking_task = None

    @property
    def user_stream(self) -> asyncio.Queue:
        return self._user_stream
