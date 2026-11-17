"""std/providers/openai.py: OpenAI, a provider that answers a log with a model behind an OpenAI-compatible chat API."""

import argparse
import asyncio
import functools
import getpass
import json
import os
import ssl
import sys
import threading
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterable, Iterator

from llvim.core import Author, Log, Request, Writer
from llvim.std import env
from llvim.std.conversation import ROLES, Entry, Field, Info, Tag, encode, entries
from llvim.std.cues import GENERATE, TOOLS, cued, receive, send, take
from llvim.std.providers import openai_settings as settings
from llvim.std.tools import Tool
from llvim.std.tools.calls import CALL, RESULT, by_user, call_id, kind, name

BODY_PREVIEW = 500  # bytes of an error response kept in the log
# Where systems keep their CA bundle, as Go's crypto/x509 looks for it. A Python built elsewhere (uv's, say) looks only where its
# builder's system keeps it, which on NixOS is nowhere.
BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Arch, NixOS
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora, RHEL
    "/etc/ssl/ca-bundle.pem",  # openSUSE
    "/etc/pki/tls/cacert.pem",  # OpenELEC
    "/etc/ssl/cert.pem",  # Alpine, macOS
)
MAX_PAUSE = 60.0  # longest wait between two tries, seconds
NO_RESULT = "[no result: the call was interrupted before it finished]"


class ApiError(RuntimeError):
    """The server refused, was unreachable, or sent something that is not a chat stream."""

    def __init__(self, message: str, retryable: bool = False, retry_after: float | None = None):
        super().__init__(message)
        self.retryable, self.retry_after = retryable, retry_after


def to_openai(tool: Tool) -> dict:
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
    }


def chat(log: list[Entry]) -> list[dict]:
    """The chat messages for a log: the entries tagged with a role, and the tool calls with their results. Thinking goes back as
    the `reasoning_content` of the assistant message after it, and only in the turn in progress.

    The API refuses an assistant message whose calls are not each followed at once by a `tool` message, so a result is found by
    its call id wherever it sits, and a call that has none gets NO_RESULT. A call the user made (`/bash`) is not the model's: it
    is a user message saying what was run and what it printed, once it has a result."""
    results = {call_id(e): e.content for e in log if kind(e) == RESULT}
    out: list[dict] = []
    open_calls: list[str | None] = []
    reasoning: list[str] = []

    def answer_calls() -> None:
        for id in open_calls:
            out.append({"role": "tool", "tool_call_id": id, "content": results.get(id, NO_RESULT)})
        open_calls.clear()

    def with_reasoning(message: dict) -> dict:
        if reasoning and "reasoning_content" not in message:
            message["reasoning_content"] = "".join(reasoning)
        reasoning.clear()
        return message

    for entry in log:
        if Tag.THINKING in entry.tags:
            reasoning.append(entry.content)
        elif kind(entry) == CALL and by_user(entry):
            answer_calls()
            if call_id(entry) in results:
                command = _command_of(entry)
                out.append(
                    {"role": "user", "content": f"I ran this in a terminal:\n$ {command}\n{results[call_id(entry)]}"}
                )
                reasoning.clear()
        elif kind(entry) == CALL:
            if not open_calls and not (out and out[-1]["role"] == "assistant" and "tool_calls" not in out[-1]):
                out.append({"role": "assistant", "content": None})
            with_reasoning(out[-1]).setdefault("tool_calls", []).append(
                {
                    "id": call_id(entry),
                    "type": "function",
                    "function": {"name": name(entry), "arguments": entry.content or "{}"},
                }
            )
            open_calls.append(call_id(entry))
        elif role := next((tag for tag in entry.tags if tag in ROLES), None):
            answer_calls()
            message = {"role": str(role), "content": entry.content}
            out.append(with_reasoning(message) if role == Tag.ASSISTANT else message)
            if role != Tag.ASSISTANT:
                reasoning.clear()  # thought before something other than an answer is not this turn's
    answer_calls()
    last_user = max((i for i, message in enumerate(out) if message["role"] == Tag.USER), default=-1)
    for message in out[:last_user]:
        message.pop("reasoning_content", None)
    return out


def _command_of(call: Entry) -> str:
    try:
        return str(json.loads(call.content).get("command", call.content))
    except (ValueError, AttributeError):
        return call.content


def stream(
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict],
    timeout: float = 60.0,
    tools: list[dict] | None = None,
) -> Iterator[tuple[str, str, dict]]:
    """The reply piece by piece, as (tag, text, call): THINKING, ASSISTANT or TOOL_CALL. For a call the text is a piece of its
    arguments, and `call` says which call it is (`index`, and `id` and `name` once the server has said them). `timeout` is how
    long the server may stay silent."""
    body = {"model": model, "messages": messages, "stream": True} | ({"tools": tools} if tools else {})
    calls: dict[int, dict] = {}
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"}
        | ({"Authorization": f"Bearer {api_key}"} if api_key else {}),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=tls()) as response:
            for raw in response:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue  # blank separators and comments
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                event = json.loads(data)
                if "error" in event:
                    raise ApiError(json.dumps(event["error"]))
                for choice in event.get("choices", []):
                    delta = choice.get("delta", {})
                    if text := delta.get("reasoning_content") or delta.get("reasoning"):
                        yield Tag.THINKING, text, {}
                    if text := delta.get("content"):
                        yield Tag.ASSISTANT, text, {}
                    for piece in delta.get("tool_calls") or []:
                        function = piece.get("function") or {}
                        call = calls.setdefault(piece.get("index", 0), {"index": piece.get("index", 0)})
                        call |= {k: v for k, v in (("id", piece.get("id")), ("name", function.get("name"))) if v}
                        arguments = function.get("arguments") or ""
                        yield CALL, arguments if isinstance(arguments, str) else json.dumps(arguments), dict(call)
    except urllib.error.HTTPError as e:
        wait = e.headers.get("Retry-After", "")
        with e:
            body = e.read(BODY_PREVIEW).decode(errors="replace")
        raise ApiError(
            f"{e.code} {body}",
            retryable=e.code == 429 or e.code >= 500,
            retry_after=float(wait) if wait.isdigit() else None,
        ) from None
    except OSError as e:  # unreachable, reset, timed out, or a certificate it cannot trust
        if isinstance(getattr(e, "reason", e), ssl.SSLCertVerificationError):
            fix = "; if your system trusts it, set SSL_CERT_FILE to your system's CA bundle"
            raise ApiError(f"{type(e).__name__}: {e}{fix}") from None  # asking again gets the same certificate
        raise ApiError(f"{type(e).__name__}: {e}", retryable=True) from None
    except ValueError as e:  # not JSON
        raise ApiError(f"{type(e).__name__}: {e}") from None
    except (AttributeError, KeyError, TypeError) as e:  # JSON, but not in the shape of a chat stream
        raise ApiError(f"the server sent something that is not a chat stream ({type(e).__name__}: {e})") from None


@functools.cache
def tls() -> ssl.SSLContext:
    """The default context, and if it trusts no root certificate, the system's CA bundle. `SSL_CERT_FILE` still wins."""
    context = ssl.create_default_context()
    if context.cert_store_stats()["x509_ca"] == 0:
        for bundle in (os.environ.get("NIX_SSL_CERT_FILE"), *BUNDLES):
            if bundle and os.path.isfile(bundle):
                context.load_verify_locations(cafile=bundle)
                break
    return context


class _Reply:
    """What the model sends, as messages: a new one each time it turns from thinking to talking or back, and one per call."""

    def __init__(self, writer: Writer, model: str):
        self.writer, self.model = writer, model
        self.key: tuple | None = None
        self.id: int | None = None
        self.called = False

    @property
    def wrote(self) -> bool:
        return self.id is not None

    def write(self, tag: str, text: str, call: dict) -> None:
        key = (tag, call.get("index"))
        if key != self.key:
            self.key, self.id = key, self.writer.append(self._header(tag, call))
        self.writer.extend(self.id, text.encode())

    def _header(self, tag: str, call: dict) -> bytes:
        if tag != CALL:
            return encode([tag], **{Field.MODEL: self.model})
        self.called = True
        id = (
            call.get("id") or f"call_{uuid.uuid4().hex[:12]}"
        )  # a header cannot change once written, so one is made up if missing
        return encode([CALL, call.get("name") or "unknown"], **{Field.MODEL: self.model, Field.CALL_ID: id})


_DONE = object()


async def _until_outranked(writer: Writer) -> None:
    while True:
        await writer.outranked_changed()
        if writer.outranked():
            return


async def _relay(pieces: Iterator[tuple[str, str]], reply: _Reply) -> bool:
    """Write the pieces into the reply as they come. False if someone outranked the writer first.

    The pieces are read in a daemon thread, which closes them when it is told to stop, so a server that has gone silent
    holds up neither the writer nor the program's exit."""
    loop = asyncio.get_running_loop()
    arrived: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()

    def put(item: object) -> None:
        try:
            loop.call_soon_threadsafe(arrived.put_nowait, item)
        except RuntimeError:
            pass  # the loop has closed

    def read() -> None:
        try:
            for piece in pieces:
                if stop.is_set():
                    break
                put(piece)
        except Exception as error:
            put(error)
        finally:
            pieces.close()
            put(_DONE)

    threading.Thread(target=read, daemon=True).start()
    outranked = asyncio.ensure_future(_until_outranked(reply.writer))
    next_piece = None
    try:
        while True:
            next_piece = asyncio.ensure_future(arrived.get())
            await asyncio.wait({next_piece, outranked}, return_when=asyncio.FIRST_COMPLETED)
            if outranked.done():
                outranked.result()
                return False
            piece = next_piece.result()
            if piece is _DONE:
                return True
            if isinstance(piece, Exception):
                raise piece
            reply.write(*piece)
    finally:
        stop.set()
        await _cancel(outranked, next_piece)


async def _reconnect(writer: Writer, error: ApiError, attempt: int, retries: int, backoff: float) -> bool:
    """Say that it waits to try again, and wait. False if someone outranked the writer meanwhile."""
    pause = min(error.retry_after if error.retry_after is not None else backoff * 2**attempt, MAX_PAUSE)
    note = f"attempting to reconnect in {pause:g}s ({attempt + 1} of {retries}): {str(error)[:200]}"
    status = writer.append(encode([Tag.STATUS], note))
    try:
        await asyncio.wait_for(_until_outranked(writer), pause)
        return False
    except TimeoutError:
        return True
    finally:
        writer.remove(status)


async def _cancel(*tasks: asyncio.Future | None) -> None:
    """Cancel the tasks and wait until they have ended, so none is left watching a writer that is released next."""
    running = [task for task in tasks if task is not None]
    for task in running:
        task.cancel()
    await asyncio.gather(*running, return_exceptions=True)


async def respond(
    log: Log,
    model: str,
    base_url: str,
    api_key: str | None = None,
    timeout: float = 60.0,
    priority: int = 0,
    retries: int = 5,
    backoff: float = 1.0,
    tools: Iterable[Tool] = (),
) -> bool:
    """Answer the log if the model is cued now. Returns whether it wrote anything."""
    writer = await take(log, GENERATE, _request(model, priority))
    if writer is None:
        return False
    async with writer:
        return await answer(log, writer, model, base_url, api_key, timeout, retries, backoff, tools)


async def answer(
    log: Log,
    writer: Writer,
    model: str,
    base_url: str,
    api_key: str | None,
    timeout: float,
    retries: int,
    backoff: float,
    tools: Iterable[Tool] = (),
) -> bool:
    """Answer the cue for the model, with the log held. Returns whether it wrote anything. If the reply made calls and was not
    cut short, the tools are cued."""
    history = chat(entries(log.read()))
    offered = [to_openai(tool) for tool in tools] or None
    reply = _Reply(writer, model)
    finished = False
    for attempt in range(retries + 1):
        try:
            finished = await _relay(stream(base_url, api_key, model, history, timeout, offered), reply)
            if finished and not reply.wrote:
                raise ApiError("the server sent an empty reply")
            break
        except ApiError as error:
            if reply.wrote or not error.retryable or attempt == retries:
                note = str(error) + (f" (after {attempt + 1} attempts)" if attempt else "")
                writer.append(encode([Tag.ERROR], note))
                break
            if not await _reconnect(writer, error, attempt, retries, backoff):
                return False
    if not reply.wrote and cued(log.read()) == GENERATE:
        return False
    if finished and reply.called:
        send(writer, TOOLS)
    await writer.commit(author=_author(model))
    return True


def _request(model: str, priority: int) -> Request:
    return Request(priority, {Info.PROVIDER: "openai", Info.MODEL: model})


def _author(model: str) -> Author:
    try:
        return Author(model)
    except ValueError:
        return Author("openai")


async def serve(
    log: Log,
    model: str,
    base_url: str,
    api_key: str | None,
    timeout: float,
    retries: int,
    priority: int,
    tools: Iterable[Tool] = (),
):
    """Answer each cue for the model, until cancelled."""
    async for writer in receive(log, GENERATE, _request(model, priority)):
        await answer(log, writer, model, base_url, api_key, timeout, retries, 1.0, tools)


def configure() -> None:
    """Ask for the settings and save them to `openai.toml`, readable only by you. The key is typed hidden."""
    try:
        current = settings.read()
    except ValueError:
        current = {}
    base_url = input(f"base URL [{current.get('base_url') or settings.URL}]: ").strip()
    key = getpass.getpass("API key (hidden; Enter keeps the saved one, - for none): ").strip()
    model = input(f"model [{current.get('model', '')}]: ").strip()
    saved = {
        "base_url": base_url or current.get("base_url", ""),
        "api_key": "" if key == "-" else key or current.get("api_key", ""),
        "model": model or current.get("model", ""),
    }
    if saved["base_url"] and not saved["base_url"].startswith(("http://", "https://")):
        sys.exit("llvim-openai: the base URL must start with http:// or https://")
    print(f"saved to {settings.save(saved)} (only you can read it)")


class OpenAI:
    """The provider as a program: `OpenAI().run()` answers the log until interrupted. `model` and `base_url` default to the
    settings (`openai_settings`), `log` to the session's (`env.log`). `tools` are offered to the model; a runner runs them."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        log: Log | None = None,
        timeout: float = 60.0,
        retries: int = 5,
        priority: int = 0,
        once: bool = False,
        tools: Iterable[Tool] = (),
    ):
        self.model, self.base_url, self.log, self.once, self.tools = model, base_url, log, once, list(tools)
        self.timeout, self.retries, self.priority = timeout, retries, priority

    def run(self) -> None:
        try:
            model, base_url, api_key = (
                self.model or settings.model(),
                self.base_url or settings.base_url(),
                settings.api_key(),
            )
        except ValueError as error:
            sys.exit(f"llvim-openai: {error}")
        if not model:
            sys.exit("llvim-openai: no model: pass --model, set $LLVIM_MODEL, or save one with --configure")
        log = self.log or env.log()
        if self.once:
            work = respond(log, model, base_url, api_key, self.timeout, self.priority, self.retries, tools=self.tools)
        else:
            work = serve(log, model, base_url, api_key, self.timeout, self.retries, self.priority, self.tools)
        try:
            asyncio.run(work)
        except KeyboardInterrupt:
            pass


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="llvim-openai", description="Answer a log with an OpenAI-compatible model.")
    ap.add_argument("log", nargs="?", default="main")
    ap.add_argument("-p", "--project", default=".", help="project folder (default: the working folder)")
    ap.add_argument("-m", "--model", help="default: $LLVIM_MODEL, else model in openai.toml")
    ap.add_argument("--base-url", help="default: $OPENAI_BASE_URL, else base_url in openai.toml, else OpenAI's")
    ap.add_argument(
        "--configure", action="store_true", help="save the base URL, key and model to openai.toml, then exit"
    )
    ap.add_argument("--timeout", type=float, default=60.0, help="seconds the server may stay silent (default: 60)")
    ap.add_argument("--retries", type=int, default=5, help="tries again after a failed connection (default: 5)")
    ap.add_argument("--priority", type=int, default=0, help="how this provider ranks when others want the log")
    ap.add_argument("--once", action="store_true", help="answer if there is something to answer, then exit")
    ap.add_argument("--no-tools", action="store_true", help="offer the model no tools (default: bash)")
    args = ap.parse_args(argv)
    if args.configure:
        return configure()
    from llvim.std.tools import bash

    log = Log(args.project, args.log)
    tools = [] if args.no_tools else [bash.TOOL]
    OpenAI(args.model, args.base_url, log, args.timeout, args.retries, args.priority, args.once, tools).run()
