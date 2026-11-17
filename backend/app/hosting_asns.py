"""Which networks count as hosting providers (#103).

A crawler that runs JavaScript and sends an ordinary Chrome user agent looks
like a visitor in every field we store. What gives it away is where it runs:
in a rented server, not on a broadband or mobile line. So a pageview whose
address belongs to one of the networks below is labelled at collection and
kept out of the statistics. See app/services/hosting_networks_service.py for
where the address ranges come from.

This is a guess, and the list is where the guess is made, so it is kept short
enough to read and review. Each number was checked against its description in
the IPtoASN file on 2026-11-17. Do not add one from memory: look up what the
file calls it first (the third column is the number, the fifth the name),
because a transit or broadband network added by mistake hides real people and
nothing will say so.

What it costs: a person browsing through a VPN or a remote desktop hosted at
one of these providers is labelled too. A website whose real audience sits
behind such a network can turn the exclusion off under its settings.

Deliberately NOT on the list, although crawlers do come from them:

  13335         Cloudflare. WARP and iCloud Private Relay put real people
                behind it.
  20940, 36183  Akamai. iCloud Private Relay's other egress network.
  54113         Fastly. The same, a third Private Relay partner.
  15169         Google's main network. Chrome's own proxies, Google Fi and
                other consumer services leave from it; Google Cloud has its
                own numbers, which are listed.
  714, 6185     Apple. Its own offices and services, and nothing to catch.

Listing any of these would remove a visible share of ordinary Safari and
mobile traffic to catch crawlers that mostly announce themselves in the user
agent anyway.
"""
from typing import Dict

#: AS number to the provider it belongs to. The name is for the reader; only
#: the number is compared.
HOSTING_ASNS: Dict[int, str] = {
    16509: "Amazon (AWS)",
    14618: "Amazon (AWS)",
    8987: "Amazon (AWS GovCloud)",
    396982: "Google Cloud",
    139070: "Google Cloud (Asia Pacific)",
    8075: "Microsoft (Azure)",
    14061: "DigitalOcean",
    16276: "OVH",
    24940: "Hetzner",
    63949: "Akamai Connected Cloud (Linode)",
    20473: "Vultr",
    45102: "Alibaba Cloud",
    37963: "Alibaba Cloud",
    134963: "Alibaba Cloud (Singapore)",
    45090: "Tencent Cloud",
    132203: "Tencent Cloud",
    136907: "Huawei Cloud",
    55990: "Huawei Cloud",
    396986: "ByteDance",
    138699: "ByteDance (TikTok)",
    31898: "Oracle Cloud",
    51167: "Contabo",
    40021: "Contabo",
    12876: "Scaleway",
    60781: "Leaseweb",
    133752: "Leaseweb (Hong Kong)",
    9009: "M247",
    212238: "Datacamp",
    60068: "Datacamp (CDN77)",
    8560: "IONOS",
    199524: "G-Core",
    135377: "UCloud",
    21859: "Zenlayer",
    59019: "Kingsoft Cloud",
    38365: "Baidu",
    53667: "FranTech (BuyVM)",
    62240: "Clouvider",
    36352: "ColoCrossing",
    29802: "Hivelocity",
    46606: "Unified Layer",
    35916: "Multacom",
    62904: "Eonix",
    49981: "WorldStream",
    197540: "netcup",
    50673: "Serverius",
    16125: "Cherry Servers",
    43350: "NForce",
    51396: "Pfcloud",
    9370: "Sakura Internet",
    7684: "Sakura Internet",
    132839: "Power Line Datacenter",
    137409: "GSL Networks",
    139341: "ACE",
    58461: "China Telecom Hangzhou IDC",
}

#: Never to be added without rereading the reasons above. A test holds the two
#: sets apart, so adding Cloudflare "just to try it" fails before it ships.
NEVER_LISTED: Dict[int, str] = {
    13335: "Cloudflare",
    20940: "Akamai",
    36183: "Akamai (Private Relay)",
    54113: "Fastly",
    15169: "Google",
    714: "Apple",
    6185: "Apple",
}
