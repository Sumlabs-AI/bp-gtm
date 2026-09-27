import pytest

from app.leads.address import address_key, split_mail_address, zip5


@pytest.mark.parametrize(
    ("street", "zip_code"),
    [
        ("1200 North Oak Street", "77002"),
        ("1200 N OAK ST", "77002-1234"),
        ("1200 N. Oak St.", 77002),
        ("1200 n oak st apt 4", "77002"),
        ("1200 N OAK ST # 4", "770021234"),
        ("01200     N     OAK      ST", "770021234"),  # Oncor's ESI ID extract layout
    ],
)
def test_variants_share_a_key(street, zip_code):
    assert address_key(street, zip_code) == "1200 N OAK ST 77002"


@pytest.mark.parametrize(
    ("street", "zip_code"),
    [
        (None, "77002"),
        (float("nan"), "77002"),
        ("", "77002"),
        ("OAK ST", "77002"),
        ("1200 OAK ST", "7700"),
        ("1 A", None),
    ],
)
def test_unusable_addresses_have_no_key(street, zip_code):
    assert address_key(street, zip_code) is None


def test_parkway_spellings_match():
    assert address_key("14006 BRIARHILLS PKY", "77077") == address_key(
        "14006 Briarhills Parkway", "77077"
    )


def test_house_number_zero_is_kept():
    assert address_key("0 OAKSHIRE DR", "77027") == "0 OAKSHIRE DR 77027"


def test_zip5():
    assert zip5("77002-1234") == "77002" and zip5(None) is None
    assert zip5(float("nan")) is None


@pytest.mark.parametrize(
    ("mail", "parts"),
    [
        (
            "15038 ROYAL SHADOWS DR, HOUSTON, TX 77082-4029",
            ("15038 ROYAL SHADOWS DR", "HOUSTON", "TX", "77082-4029"),
        ),
        (
            "PO BOX 12, UNIT 4, SOUTH HOUSTON, TX 77587",
            ("PO BOX 12, UNIT 4", "SOUTH HOUSTON", "TX", "77587"),
        ),
        # An empty ZIP+4 in the source leaves a dangling hyphen.
        ("12 OAK LN, SPRING, TX 77386-", ("12 OAK LN", "SPRING", "TX", "77386")),
        # Not the US "CITY, ST ZIP" shape: the whole string stays in the street line.
        (
            "12 HIGH ST, LONDON, SW1A 1AA, UNITED KINGDOM",
            ("12 HIGH ST, LONDON, SW1A 1AA, UNITED KINGDOM", None, None, None),
        ),
        (None, (None, None, None, None)),
    ],
)
def test_split_mail_address(mail, parts):
    assert split_mail_address(mail) == parts
