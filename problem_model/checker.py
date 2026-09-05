from dmoj.result import CheckerResult
from dmoj.utils.unicode import utf8text

def check(process_output, judge_output, judge_input, point_value, submission_source, **kwargs):
    result = normalize(utf8text(process_output))
    answer = normalize(utf8text(judge_output))
    input = normalize(ut)
    
    if result != answer:
        return CheckerResult(False, 0)

    return CheckerResult(True, point_value)

def normalize(data):
    return data.split()
