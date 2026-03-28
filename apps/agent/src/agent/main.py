import logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("agent")


def main() -> None:
    logger.info("Proxmox host agent placeholder started")


if __name__ == "__main__":
    main()
