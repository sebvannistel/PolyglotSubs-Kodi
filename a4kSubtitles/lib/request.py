# -*- coding: utf-8 -*-

import ssl
import traceback

import requests
import urllib3
from requests import adapters
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_result

from . import logger
from .kodi import get_int_setting
from .third_party.cloudscraper import cloudscraper


class TLSAdapter(adapters.HTTPAdapter):
    """
    A TLS adapter that allows for custom SSL/TLS versions.
    """

    def init_poolmanager(self, connections, maxsize, block=False):
        """
        Initializes the pool manager.

        Args:
            connections (int): The number of connections.
            maxsize (int): The maximum size of the pool.
            block (bool, optional): Whether to block when no free connections are available. Defaults to False.
        """
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        self.poolmanager = urllib3.poolmanager.PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_version=ssl.PROTOCOL_TLSv1_2,
            ssl_context=ctx,
        )


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _is_retryable_status_code(response):
    """
    Checks if the response status code indicates that the request should be retried.
    """
    # The original logic retried on 502, 503, 429, 409, 403
    # It also had special handling: if 503 or 403, it jumped retry count to 5 (effectively last retry).
    # We will use a simpler approach here: retry on these codes.
    return response.status_code in [502, 503, 429, 409, 403]


def execute(core, request, progress=True, session=None):
    """
    Executes a request using tenacity for retries.

    Args:
        core (module): The core module.
        request (dict): The request to execute.
        progress (bool, optional): Whether to show a progress dialog. Defaults to True.
        session (requests.Session, optional): The session to use. Defaults to None.

    Returns:
        requests.Response: The response.
    """
    try:
        default_timeout = get_int_setting("general.timeout")
    except:
        default_timeout = 10
    request.setdefault("timeout", default_timeout)

    if progress and core.progress_dialog and not core.progress_dialog.dialog:
        core.progress_dialog.open()

    next_fn = request.pop("next", None)
    error_fn = request.pop("error", None)
    validate_fn = request.pop("validate", None) # Custom validation/retry logic from caller

    cfscrape = "cfscrape" in request
    request.pop("cfscrape", None)

    if next_fn:
        request.pop("stream", None)

    # Define the retry strategy
    # Original logic: max 5 retries (approx).
    # Wait 3 seconds between retries (unless 503/403 which fast-forwarded).
    # Tenacity allows declarative config.

    # We use a wrapper function to apply tenacity only to the request execution part
    @retry(
        stop=stop_after_attempt(6), # 1 initial + 5 retries
        wait=wait_fixed(3),
        retry=retry_if_result(lambda r: _is_retryable_status_code(r) if hasattr(r, 'status_code') else False),
        reraise=True
    )
    def _do_request(req_session):
        logger.debug(
            "%s ^ - %s, %s"
            % (
                request["method"],
                request["url"],
                core.json.dumps(request.get("params", {})),
            )
        )

        try:
            if cfscrape:
                current_session = req_session or cloudscraper.create_scraper(interpreter="native")
                # cloudscraper might need verify=False handling on error as per original code
                resp = current_session.request(**request)
            else:
                current_session = req_session or requests.session()
                if not req_session: # mount only if we created it
                    current_session.mount("https://", TLSAdapter())
                resp = current_session.request(**request)

            exc = ""
            return resp

        except Exception:
            # Original code swallowed exceptions and returned a dummy 500 response
            # to allow retry logic to handle it (or not).
            # With tenacity, we can just let exceptions bubble up if we wanted to retry on exception.
            # But maintaining original behavior:
            exc = traceback.format_exc()

            if cfscrape:
                # Original fallback for cfscrape
                try:
                    current_session = req_session or cloudscraper.create_scraper(interpreter="native")
                    resp = current_session.request(verify=False, **request)
                    exc = ""
                    return resp
                except:
                    exc = traceback.format_exc()

            # Create dummy response object
            dummy = lambda: None
            dummy.text = ""
            dummy.content = ""
            dummy.status_code = 500

            logger.debug(
                "%s $ - %s - %s, %s"
                % (request["method"], request["url"], 500, exc)
            )
            return dummy

    # Execute the request
    try:
        response = _do_request(session)
    except Exception:
        # Should be caught by inner try/except but just in case
        response = lambda: None
        response.status_code = 500
        response.text = ""
        response.content = ""

    logger.debug(
        "%s $ - %s - %s"
        % (request["method"], request["url"], response.status_code)
    )

    # Handle custom validation if provided (overrides standard retry logic if it triggers a retry)
    # The original code allowed 'validate' to return a new request to execute recursively.
    # This is complex to map exactly to tenacity if 'validate' changes the request.
    # However, 'validate' was mostly used for the default retry logic.
    # If 'validate' is custom, we should respect it.

    if validate_fn:
         alt_request = validate_fn(response)
         if alt_request:
             # Recursive call as per original design if validation fails/requires retry with new params
             # We pass back the functions we popped
             if next_fn: alt_request['next'] = next_fn
             if error_fn: alt_request['error'] = error_fn
             if cfscrape: alt_request['cfscrape'] = True # restore flag if needed
             # Note: 'validate' is usually consumed, so we don't put it back unless intended.
             return execute(core, alt_request, progress, session)

    # Handle 'next' (chaining)
    if next_fn and response.status_code == 200:
        next_request = next_fn(response)
        if next_request:
            return execute(core, next_request, progress, session)
        else:
            return None

    # Handle 'error'
    if error_fn and response.status_code >= 400:
        next_request = error_fn(response)
        if next_request:
            return execute(core, next_request, progress, session)
        else:
            return None

    return response
