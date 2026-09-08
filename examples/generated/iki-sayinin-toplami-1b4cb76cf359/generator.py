import json

cases = [
    {"input": "0 0\n", "category": "edge"},
    {"input": "-1000000000 1000000000\n", "category": "boundary"},
    {"input": "1000000000 1000000000\n", "category": "boundary"},
    {"input": "-1000000000 -1000000000\n", "category": "boundary"},
    {"input": "17 -4\n", "category": "random"}
]
print(json.dumps(cases))
