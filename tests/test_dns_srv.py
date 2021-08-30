import pytest

import psycopg
from psycopg.conninfo import conninfo_to_dict

from .test_dns import import_dnspython

samples_ok = [
    ("", "", None),
    ("host=_pg._tcp.foo.com", "host=db1.example.com port=5432", None),
    ("", "host=db1.example.com port=5432", {"PGHOST": "_pg._tcp.foo.com"}),
    (
        "host=foo.com,_pg._tcp.foo.com",
        "host=foo.com,db1.example.com port=,5432",
        None,
    ),
    (
        "host=_pg._tcp.dot.com,foo.com,_pg._tcp.foo.com",
        "host=foo.com,db1.example.com port=,5432",
        None,
    ),
    (
        "host=_pg._tcp.bar.com",
        (
            "host=db1.example.com,db4.example.com,db3.example.com,db2.example.com"
            " port=5432,5432,5433,5432"
        ),
        None,
    ),
    (
        "host=service.foo.com port=srv",
        ("host=service.example.com port=15432"),
        None,
    ),
    # No resolution
    (
        "host=_pg._tcp.foo.com hostaddr=1.1.1.1",
        "host=_pg._tcp.foo.com hostaddr=1.1.1.1",
        None,
    ),
]


@pytest.mark.parametrize("conninfo, want, env", samples_ok)
def test_srv(conninfo, want, env, fake_srv, retries, monkeypatch):
    if env:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
    # retries are needed because weight order is random, although wrong order
    # is unlikely.
    for retry in retries:
        with retry:
            params = conninfo_to_dict(conninfo)
            params = psycopg._dns.resolve_srv(params)
            assert conninfo_to_dict(want) == params


@pytest.mark.asyncio
@pytest.mark.parametrize("conninfo, want, env", samples_ok)
async def test_srv_async(conninfo, want, env, fake_srv, retries, monkeypatch):
    if env:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
    async for retry in retries:
        with retry:
            params = conninfo_to_dict(conninfo)
            params = await psycopg._dns.resolve_srv_async(params)
            assert conninfo_to_dict(want) == params


samples_bad = [
    ("host=_pg._tcp.dot.com", None),
    ("host=_pg._tcp.foo.com port=1,2", None),
]


@pytest.mark.parametrize("conninfo,  env", samples_bad)
def test_srv_bad(conninfo, env, fake_srv, monkeypatch):
    if env:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
    params = conninfo_to_dict(conninfo)
    with pytest.raises(psycopg.OperationalError):
        psycopg._dns.resolve_srv(params)


@pytest.mark.asyncio
@pytest.mark.parametrize("conninfo,  env", samples_bad)
async def test_srv_bad_async(conninfo, env, fake_srv, monkeypatch):
    if env:
        for k, v in env.items():
            monkeypatch.setenv(k, v)
    params = conninfo_to_dict(conninfo)
    with pytest.raises(psycopg.OperationalError):
        await psycopg._dns.resolve_srv_async(params)


@pytest.fixture
def fake_srv(monkeypatch):
    import_dnspython()

    from dns.rdtypes.IN.A import A
    from dns.rdtypes.IN.SRV import SRV
    from dns.exception import DNSException

    fake_hosts = {
        ("_pg._tcp.dot.com", "SRV"): ["0 0 5432 ."],
        ("_pg._tcp.foo.com", "SRV"): ["0 0 5432 db1.example.com."],
        ("_pg._tcp.bar.com", "SRV"): [
            "1 0 5432 db2.example.com.",
            "1 255 5433 db3.example.com.",
            "0 0 5432 db1.example.com.",
            "1 65535 5432 db4.example.com.",
        ],
        ("service.foo.com", "SRV"): ["0 0 15432 service.example.com."],
    }

    def fake_srv_(qname, rdtype):
        try:
            ans = fake_hosts[qname, rdtype]
        except KeyError:
            raise DNSException(f"unknown test host: {qname} {rdtype}")
        rv = []

        if rdtype == "A":
            for entry in ans:
                rv.append(A("IN", "A", entry))
        else:
            for entry in ans:
                pri, w, port, target = entry.split()
                rv.append(
                    SRV("IN", "SRV", int(pri), int(w), int(port), target)
                )

        return rv

    async def afake_srv_(qname, rdtype):
        return fake_srv(qname, rdtype)

    monkeypatch.setattr(psycopg._dns.resolver, "resolve", fake_srv_)
    monkeypatch.setattr(psycopg._dns.async_resolver, "resolve", afake_srv_)