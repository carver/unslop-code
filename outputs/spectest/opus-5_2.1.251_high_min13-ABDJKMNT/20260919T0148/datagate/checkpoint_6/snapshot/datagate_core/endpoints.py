"""The `endpoint` value the ingestion routes report, relative or absolute."""


def endpoint_url(identifier, host, require_tls):
    """The dataset path, as an absolute `https://` URL on `host` when TLS is required.

    The host is the one the request arrived on, port included (AMBIGUITIES T68).
    """
    path = f"/datasets/{identifier}"
    return f"https://{host}{path}" if require_tls else path
