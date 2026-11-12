from app.plate_matcher import normalize, search, similarity

CARS = [
    {"slot_id": "A05", "plate": "KA05MH1234", "plate_conf": 0.95},
    {"slot_id": "C11", "plate": "TN09AB4521", "plate_conf": 0.95},
    {"slot_id": "D17", "plate": "KL07?Z88?1", "plate_conf": 0.55},   # camera missed 2 chars
    {"slot_id": "B03", "plate": "MH4321", "plate_conf": 0.6},        # left part hidden
    {"slot_id": "B04", "plate": "KA05MH1239", "plate_conf": 0.95},   # look-alike
]


def test_normalize():
    assert normalize(" ka-05 mh 1234 ") == "KA05MH1234"
    assert normalize("KA05*H1234") == "KA05?H1234"


def test_exact_match_is_first():
    r = search("ka 05 mh 1234", CARS)
    assert r[0].slot_id == "A05" and r[0].exact
    assert any(m.slot_id == "B04" for m in r)  # near-identical plate still suggested


def test_user_types_only_last_digits():
    r = search("4521", CARS)
    assert r[0].slot_id == "C11"


def test_camera_read_partial_plate():
    # visitor types full plate; camera stored it with unknown characters
    r = search("KL07AZ8851", CARS)
    assert r[0].slot_id == "D17"


def test_camera_saw_only_fragment():
    r = search("DL08MH4321", CARS)
    assert r[0].slot_id == "B03"


def test_ocr_confusions_cost_less():
    assert similarity("KA05MH1234", "KAO5MH1234") > similarity("KA05MH1234", "KAX5MH1234")


def test_too_short_query_returns_nothing():
    assert search("12", CARS) == []


def test_unrelated_plate_not_suggested():
    assert search("ZZ99QQ0000", CARS) == []
