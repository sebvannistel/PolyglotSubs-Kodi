# -*- coding: utf-8 -*-


def build_search_requests(core, service_name, meta):
    """
    Builds the search requests for the subdl service.

    Args:
        core (module): The core module.
        service_name (str): The name of the service.
        meta (dict): The metadata of the video.

    Returns:
        list: A list of search requests.
    """
    apikey = core.kodi.get_setting(service_name, "apikey")

    if not apikey:
        core.kodi.notification(
            "SubDL requires API Key! Enter it in the addon Settings->Accounts or disable the service."
        )
        core.logger.error("%s - API Key is missing" % service_name)
        return []

    lang_ids = core.utils.get_lang_ids(meta.languages, core.kodi.xbmc.ISO_639_1)
    params = {
        "api_key": apikey,
        "languages": ",".join(lang_ids),
        "type": "movie" if not meta.is_tvshow else "tv",
        "subs_per_page": 30,
    }

    if meta.is_tvshow:
        params.update(
            {
                "film_name": meta.tvshow,
                "file_name": meta.filename_without_ext,
                "season_number": meta.season,
                "episode_number": meta.episode,
            }
        )

        if meta.tvshow_year_thread:
            meta.tvshow_year_thread.join()
        if meta.tvshow_year:
            params["year"] = meta.tvshow_year
    else:
        params.update(
            {
                "imdb_id": meta.imdb_id,
                "year": meta.year,
            }
        )

    request = {
        "method": "GET",
        "url": "https://api.subdl.com/api/v1/subtitles",
        "params": params,
    }

    return [request]


def parse_search_response(core, service_name, meta, response):
    """
    Parses the search response from the subdl service.

    Args:
        core (module): The core module.
        service_name (str): The name of the service.
        meta (dict): The metadata of the video.
        response (requests.Response): The response from the service.

    Returns:
        list: A list of subtitle results.
    """
    try:
        results = core.json.loads(response.text)
    except Exception as exc:
        core.logger.error("%s - %s" % (service_name, exc))
        return []

    if not results.get("status", False):
        core.logger.error(
            "%s - %s" % (service_name, results.get("message", "Unknown error"))
        )
        return []

    core.logger.debug(
        "%s - Found %d subtitles" % (service_name, len(results["subtitles"]))
    )

    service = core.services[service_name]
    lang_ids = core.utils.get_lang_ids(meta.languages, core.kodi.xbmc.ISO_639_1)

    def map_result(result):
        filename = result["release_name"]
        lang_code = result["language"].lower()
        lang = meta.languages[lang_ids.index(lang_code)]

        return {
            "service_name": service_name,
            "service": service.display_name,
            "lang": lang,
            "name": filename,
            "rating": 0,
            "lang_code": lang_code,
            "sync": "false",
            "impaired": "true" if result["hi"] else "false",
            "color": "springgreen",
            "action_args": {
                "url": result["url"],
                "lang": lang,
                "filename": filename,
            },
        }

    return list(map(map_result, results["subtitles"]))


def build_download_request(core, service_name, args):
    """
    Builds the download request for the subdl service.

    Args:
        core (module): The core module.
        service_name (str): The name of the service.
        args (dict): The arguments for the download.

    Returns:
        dict: The download request.
    """
    request = {"method": "GET", "url": "https://dl.subdl.com" + args["url"]}

    core.logger.debug("%s - Downloading %s" % (service_name, args["filename"]))

    return request
