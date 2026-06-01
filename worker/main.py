import asyncio
import logging
import signal

from supervisor import WorkerSupervisor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nightwatch.worker")


async def main():
    supervisor = WorkerSupervisor()

    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def handle_signal():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    task = asyncio.create_task(supervisor.run())

    await shutdown_event.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    logger.info("Worker shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
