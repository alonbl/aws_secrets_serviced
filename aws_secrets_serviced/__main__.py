# -*- coding: utf-8 -*-
import argparse
import configparser
import ctypes
import importlib.metadata
import logging
import os
import pathlib
import re
import shutil
import signal
import time
import typing

import boto3
import sdnotify

MS_NOSUID = 2
MS_NODEV = 4
MS_NOEXEC = 8

LOG_LEVELS: typing.Dict[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


SPLIT_COMMA_RE: typing.Final = re.compile(r"\s*,\s*")


def _setup_argparser(
    distribution: importlib.metadata.Distribution,
) -> argparse.ArgumentParser:

    name = getattr(
        distribution,
        "name",
        "aws_secrets_serviced",
    )  # TODO: remove python-3.10  # pylint: disable=fixme

    parser = argparse.ArgumentParser(
        prog=name,
        description="AWS secrets for services",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{name}-{distribution.version}",
    )
    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        choices=LOG_LEVELS.keys(),
        help=f"Log level {', '.join(LOG_LEVELS.keys())}",
    )
    parser.add_argument(
        "--log-file",
        metavar="FILE",
        help="Log file to use, default is stdout",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        action="append",
        required=True,
        help="Configuration file, may be specified multiple times",
    )

    return parser


def _setup_log(
    args: argparse.Namespace,
    config: configparser.SectionProxy,
) -> None:
    handler = logging.StreamHandler()
    log_file = args.log_file or config.get("log_file")
    if log_file:
        handler.setStream(
            open(  # pylint: disable=consider-using-with
                log_file,
                "a",
                encoding="utf-8",
            ),
        )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            config.get(
                "logformat",
                fallback="%(asctime)s - %(levelname)-8s %(name)-15s %(message)s",
            ),
        ),
    )
    logging.getLogger(None).addHandler(handler)

    logger = logging.getLogger("aws_secrets_serviced")
    logger.setLevel(LOG_LEVELS.get(args.log_level, config.get("log_level", logging.INFO)))


def main() -> None:  # pylint: disable=too-many-locals, too-many-statements
    try:
        distribution = importlib.metadata.distribution(
            "aws_secrets_serviced",
        )
    except importlib.metadata.PackageNotFoundError:
        distribution = importlib.metadata.PathDistribution(path=pathlib.Path())

    args = _setup_argparser(distribution).parse_args()
    config = configparser.ConfigParser()
    for config_file in args.config:
        config.read(config_file)

    _setup_log(args, config["main"])
    logger = logging.getLogger("aws_secrets_serviced")

    logger.info("Startup, version=%s", distribution.version)
    logger.debug("Args: %r", args)
    logger.debug("Config: %r", dict(((x, dict(y)) for x, y in config.items())))

    secrets_sections = config["main"].get("secrets")
    if not secrets_sections:
        raise RuntimeError("Please specify 'secrets' in configuration")
    mountpoint = config["main"].get("mountpoint")
    if not mountpoint:
        raise RuntimeError("Please specify 'mountpoint' in configuration")

    secrets_names = SPLIT_COMMA_RE.split(secrets_sections.strip())

    session = boto3.session.Session()

    class MyExit(RuntimeError):
        pass

    def shutdown() -> None:
        raise MyExit()

    signal.signal(
        signal.SIGTERM,
        lambda x, y: shutdown(),
    )
    signal.signal(
        signal.SIGINT,
        lambda x, y: shutdown(),
    )

    _libc = ctypes.cdll.LoadLibrary("libc.so.6")
    old_umask = os.umask(0o077)

    try:
        result = _libc.mount(
            ctypes.c_char_p("none".encode("utf8")),
            ctypes.c_char_p(mountpoint.encode("utf8")),
            ctypes.c_char_p("tmpfs".encode("utf8")),
            MS_NOSUID | MS_NODEV | MS_NOEXEC,
            0,
        )
        if result != 0:
            raise OSError(ctypes.get_errno())

        for secret_name in secrets_names:
            secret = config[secret_name]

            client = session.client(service_name="secretsmanager", region_name=secret["region"])
            get_secret_value_response = client.get_secret_value(SecretId=secret["secret"])

            dest = os.path.join(mountpoint, f"./{secret['dest']}")

            logger.info("Create '%s'", dest)
            os.umask(0o022)
            os.makedirs(os.path.dirname(dest), mode=0o755, exist_ok=True)

            os.umask(0o077)
            with open(dest, "wb") as f:  # pylint: disable=invalid-name
                f.write(get_secret_value_response["SecretString"].encode("utf8"))

            os.chmod(dest, int(secret["mode"], 8))
            user, group = secret["owner"].split(":")
            shutil.chown(dest, user, group)

        sdnotify.SystemdNotifier().notify("READY=1")
        while True:
            time.sleep(24 * 60 * 60)

    except MyExit:
        pass
    finally:
        os.umask(old_umask)
        result = _libc.umount(ctypes.c_char_p(mountpoint.encode("utf8")))
        if result != 0:
            raise OSError(ctypes.get_errno())


if __name__ == "__main__":
    main()
