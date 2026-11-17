import copy
import datetime as dt

from shorts.facts import derived_facts, release_date, validate_facts
from shorts.models import Scene, Script
from shorts.verify import assign_badges, passed, verify_script


def make(scenes, fmt="top3", title="GTA 6: test"):
    s = Script(id="t", format=fmt, title=title,
               scenes=[Scene(kind="hook", narration="Here is a quick GTA 6 test for you.", on_screen="TEST")] + scenes
               + [Scene(kind="cta", narration="What do you think? Tell me in the comments below right now.",
                        on_screen="COMMENT")])
    return s


def codes(issues):
    return {i.code for i in issues if i.level == "error"}


def test_seed_facts_are_valid(facts, today):
    errors = [i for i in validate_facts(facts, today) if i.level == "error"]
    assert errors == []
    assert release_date(facts) == dt.date(2026, 11, 19)


def test_countdown_is_derived_from_release_date(facts, today):
    d = derived_facts(facts, today)
    assert d["days_until_release"].claim == "GTA VI launches in 2 days."
    later = dt.date(2026, 11, 25)
    assert derived_facts(facts, later) == {}            # release_date is stale by then: nothing derived
    facts["release_date"].verified_on = later           # ...until someone re-verifies it
    after = derived_facts(facts, later)
    assert "days_since_release" in after and "days_until_release" not in after


def test_stale_and_expired_facts_are_blocked(facts):
    late = dt.date(2026, 12, 1)
    assert facts["release_date"].is_stale(late)          # review_after_days: 4
    assert facts["review_embargo"].is_expired(late)      # valid_until 2026-11-19
    assert not facts["six_regions"].is_stale(late)


def test_grounded_script_passes(pool, facts, today):
    s = make([Scene("point", "Rockstar has revealed six regions, including Vice City and Grassrivers. "
                             "That is a lot of ground to cover.", "6 REGIONS", ["six_regions"]),
              Scene("point", "Standard Edition is $79.99 and Ultimate is $99.99 in the US, so plan ahead.",
                    "$79.99", ["price_us"])])
    issues = verify_script(assign_badges(s, pool), pool, facts, today, min_words=20)
    assert passed(issues), issues


def test_invented_number_is_caught(pool, facts, today):
    s = make([Scene("point", "Standard Edition is $69.99, which is a steal for a game this big, honestly.",
                    "$69.99", ["price_us"])])
    assert "unsupported_number" in codes(verify_script(s, pool, facts, today, min_words=20))


def test_claim_without_citation_is_caught(pool, facts, today):
    s = make([Scene("point", "It launches on November 19, 2026 and you can play at midnight everywhere.",
                    "NOV 19", [])])
    assert "uncited_claim" in codes(verify_script(s, pool, facts, today, min_words=20))


def test_rumor_must_be_labelled(pool, facts, today):
    s = make([Scene("rumor", "Reviews go live November 18, one day before launch. Get ready for scores.",
                    "REVIEWS", ["review_embargo"])])
    assert "unlabelled_rumor" in codes(verify_script(assign_badges(s, pool), pool, facts, today, min_words=20))
    s.scenes[1].narration = "Insiders report reviews go live November 18. Rockstar hasn't confirmed that."
    assert "unlabelled_rumor" not in codes(verify_script(s, pool, facts, today, min_words=20))
    assert s.scenes[1].badge == "RUMOR"


def test_reported_fact_needs_attribution(pool, facts, today):
    s = make([Scene("point", "Trailer 2 was viewed 475 million times across platforms in 24 hours. Wild numbers.",
                    "475M", ["trailer2_views"])])
    assert "unattributed" in codes(verify_script(s, pool, facts, today, min_words=20))


def test_myth_only_in_myth_format_and_must_be_corrected(pool, facts, today):
    s = make([Scene("myth", "The myth: GTA 6 launches on PC on day one. That is false, sorry everyone.",
                    "PC?", ["myth_pc_day_one"])], fmt="top3")
    c = codes(verify_script(s, pool, facts, today, min_words=20))
    assert "myth_outside_format" in c and "no_rebuttal" in c


def test_stale_fact_is_rejected(facts):
    late = dt.date(2026, 12, 1)
    from shorts.facts import usable_facts
    pool = usable_facts(facts, late)
    s = make([Scene("point", "It launches Thursday, November 19, 2026, and the hype is unreal right now.",
                    "NOV 19", ["release_date"])])
    assert "stale_fact" in codes(verify_script(s, pool, facts, late, min_words=20))


def test_rumor_never_in_title(pool, facts, today):
    s = make([Scene("rumor", "Insiders report reviews go live November 18. Rockstar hasn't confirmed it.",
                    "REVIEWS NOV 18?", ["review_embargo"])], title="GTA 6 reviews nov 18 confirmed")
    c = codes(verify_script(assign_badges(s, pool), pool, facts, today, min_words=20))
    assert "rumor_in_title" in c or "title_unconfirmed_number" in c


def test_banned_phrases_and_length(pool, facts, today):
    s = make([Scene("point", "Get the GTA 6 free download now before it is gone forever and ever, trust me.",
                    "FREE", ["setting"])])
    assert "banned_phrase" in codes(verify_script(s, pool, facts, today, min_words=20))
    short = make([])
    assert "too_short" in codes(verify_script(short, pool, facts, today))


def test_facts_validation_catches_bad_entries(facts, today):
    broken = copy.deepcopy(facts)
    broken["six_regions"].sources = []
    broken["myth_pc_day_one"].rebuttal = "missing"
    c = {i.code for i in validate_facts(broken, today) if i.level == "error"}
    assert {"no_source", "no_rebuttal"} <= c
