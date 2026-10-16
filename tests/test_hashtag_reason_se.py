from src import fit_graded

def test_stuffed():
    assert fit_graded.is_hashtag_stuffed("#LLM #AI #WEIRD #agents #econ #synthetic")
    assert not fit_graded.is_hashtag_stuffed("LLM respondents reproduce WEIRD bias in surveys across non-Western samples #AI")
