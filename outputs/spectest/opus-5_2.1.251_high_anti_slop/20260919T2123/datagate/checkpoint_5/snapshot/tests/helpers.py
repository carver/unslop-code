"""Request helpers shared by the test modules."""


def convert(client, base_url, fixture, **params):
    return client.get("/convert", query_string={"source": f"{base_url}/{fixture}", **params})


def endpoint_of(client, base_url, fixture, **params):
    return convert(client, base_url, fixture, **params).get_json()["endpoint"]


def load(client, base_url, fixture, **params):
    """Convert a fixture and return the payload of its dataset endpoint."""
    return client.get(endpoint_of(client, base_url, fixture, **params)).get_json()


def read(client, base_url, fixture, **params):
    """Convert a fixture and read its dataset endpoint with the given query parameters."""
    return client.get(endpoint_of(client, base_url, fixture), query_string=params)


def names(response):
    return [row[0] for row in response.get_json()["rows"]]
