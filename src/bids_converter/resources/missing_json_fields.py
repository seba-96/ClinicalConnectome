"""Default JSON fields injected when matching files miss required keys.

Users can pass a custom file via --missing-json-fields-file.
"""

file_to_json_fields = {
    # Example:
    # "sub-*/func/*_bold.json": {"TaskName": "rest"},
    #
    # Subject-range example (numeric subject suffix 0001-0100 only):
    # "0001-0100": {
    #     "Flair": {"TaskName": "rest"},
    # },
}

